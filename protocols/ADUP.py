"""
protocols/ADUP.py — Adaptive Downward/Upward Protocol (ADUP)

Based on: "Adaptive Downward/Upward Protocol" (ADUP.md)
Implements RRD+ for uplink + sink-driven downlink routing.

Uplink (Node → Sink):
- Each node maintains a parent set (neighbours with lower Rank)
- Best next-hop selected by (Rank ASC, RSSI DESC)
- Uplink DataPacket carries next_hop_id so sink builds a dynamic next-hop table
- Rank updated dynamically via link-quality + movement-direction monitoring

Downlink (Sink → Node):
- Sink builds a source route using Algorithm 1 (ADUP §3.3)
- Route embedded in DownlinkPacket; relay nodes use route_offset to forward
- Route: [hop_nearest_sink, ..., dest_node]  (reversed after build)

Control messages (RRD+ beacons):
- Interval = Base_interval + Rank × Time_unit  (dynamic, §3.1.4)
- Carry Rank value; receivers update parent set accordingly

RSSI zones (§3.1.2):
- Safety zone   : RSSI ≥ SAFETY_THRESHOLD
- Hysteresis zone: HYSTERESIS_THRESHOLD ≤ RSSI < SAFETY_THRESHOLD
- Danger zone   : RSSI < HYSTERESIS_THRESHOLD
"""
from __future__ import annotations

import random
import math
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

import simpy

from models.node import SensorNode
from models.packet import DataPacket, BeaconPacket, DropReason, Packet, PacketType

# ---------------------------------------------------------------------------
# ADUP-specific packet types
# ---------------------------------------------------------------------------

class ADUPControlPacket(BeaconPacket):
    """Control message broadcast by nodes carrying Rank value (§3.1.4)."""
    def __init__(self, source_id: int, dest_id: int, creation_time: float,
                 rank: int, a_value: int):
        super().__init__(source_id=source_id, dest_id=dest_id,
                         size_bytes=4, creation_time=creation_time,
                         gradient_level=rank)
        self.rank:    int = rank
        self.a_value: int = a_value   # hop-count from sink (used in Rank formula)


class ADUPUplinkPacket(DataPacket):
    """Uplink data packet carrying next_hop_id for sink's next-hop table (§3.2)."""
    def __init__(self, source_id: int, dest_id: int, size_bytes: int,
                 creation_time: float, next_hop_id: int, ttl: int = 20):
        super().__init__(source_id=source_id, dest_id=dest_id,
                         size_bytes=size_bytes, creation_time=creation_time,
                         ttl=ttl)
        self.next_hop_id: int = next_hop_id   # ID of forwarder toward sink


class ADUPDownlinkPacket(DataPacket):
    """Downlink packet with embedded source route (§3.3, Figure 5).

    route: [ID_nearest_to_sink, ..., ID_dest]   (ordered sink→dest)
    route_offset: index of current next-hop in route list.
    """
    def __init__(self, source_id: int, dest_id: int, size_bytes: int,
                 creation_time: float, route: List[int], ttl: int = 30):
        super().__init__(source_id=source_id, dest_id=dest_id,
                         size_bytes=size_bytes, creation_time=creation_time,
                         ttl=ttl)
        self.route:        List[int] = route   # ordered list of node IDs to traverse
        self.route_offset: int       = 0       # points to current entry in route


# ---------------------------------------------------------------------------
# ADUP Rank constants  (§3.1.3)
# ---------------------------------------------------------------------------
ROOT_RANK:           int   = 0
MIN_HOP_RANK_INC:    int   = 1
SAFETY_THRESHOLD_DB: float = -60.0   # dBm — Safety zone boundary
HYSTERESIS_DB:       float = 5.0     # dBm — hysteresis added to Old RSSI
# Hysteresis threshold = SAFETY_THRESHOLD - HYSTERESIS_DB
HYSTERESIS_THRESHOLD_DB: float = SAFETY_THRESHOLD_DB - HYSTERESIS_DB  # -65.0

# Control message interval parameters  (§3.1.4, Eq. 2)
BASE_INTERVAL_S: float = 2.0    # smallest interval (sink)
TIME_UNIT_S:     float = 1.0    # increment per Rank unit


# ---------------------------------------------------------------------------
# Per-node ADUP state
# ---------------------------------------------------------------------------

class ADUPNodeState:
    """All mutable per-node routing state for ADUP/RRD+."""

    def __init__(self, node: SensorNode, is_sink: bool):
        self.node     = node
        self.is_sink  = is_sink

        # Rank (§3.1.3): ROOT_RANK for sink, computed for others
        self.rank: int = ROOT_RANK if is_sink else 255

        # a_value = hop distance from sink used in Rank formula
        self.a_value: int = 0

        # Parent set: nb_id → (rank, old_rssi, new_rssi)
        self.parent_set: Dict[int, Tuple[int, float, float]] = {}

        # Last seen timestamp per neighbour (for route timeout)
        self.nb_last_seen: Dict[int, float] = {}

        # Control message interval (dynamic, §3.1.4)
        self.ctrl_interval: float = BASE_INTERVAL_S + self.rank * TIME_UNIT_S

        # Hold-down until timestamp (prevents rank oscillation)
        self.hold_down_until: float = 0.0

        # Random start delay
        self.start_delay: float = random.uniform(0.0, 5.0)


# ---------------------------------------------------------------------------
# Main routing class
# ---------------------------------------------------------------------------

class ADUPRouting:
    """
    ADUP protocol — same public interface as GradientRouting / FloodingRouting.
    """

    def __init__(self, network, channel, metrics, settings):
        self.network  = network
        self.channel  = channel
        self.metrics  = metrics
        self.settings = settings
        self.env: simpy.Environment = network.env

        # Per-node state
        self._state: Dict[int, ADUPNodeState] = {
            node.id: ADUPNodeState(node, node.is_sink)
            for node in network.nodes
        }

        # Sink's dynamic next-hop table: dest_id → next_hop_id  (§3.2)
        self._nexthop_table: Dict[int, int] = {}

        # Wire RX callback
        for node in network.nodes:
            node._on_receive = self._on_receive

    # =========================================================================
    # Setup Phase — BFS warm-start (identical to GradientRouting)
    # =========================================================================

    def run_setup_phase(self) -> None:
        """BFS from sink to assign initial Rank values and seed parent sets."""
        sink = self.network.sink
        visited: set[int] = {sink.id}
        q: deque[SensorNode] = deque([sink])

        while q:
            cur = q.popleft()
            cur_state = self._state[cur.id]
            for nb in cur.neighbors:
                if nb.id not in visited:
                    dist   = cur.distance_to(nb)
                    rssi   = cur.calculate_rssi(dist)
                    new_a  = cur_state.a_value + 1
                    new_rank = ROOT_RANK + new_a * MIN_HOP_RANK_INC
                    nb_state = self._state[nb.id]
                    nb_state.a_value = new_a
                    nb_state.rank    = new_rank
                    nb_state.ctrl_interval = BASE_INTERVAL_S + new_rank * TIME_UNIT_S
                    # Seed parent set with current node
                    nb_state.parent_set[cur.id] = (cur_state.rank, rssi, rssi)
                    nb_state.nb_last_seen[cur.id] = 0.0
                    nb.gradient_level = float(new_rank)
                    visited.add(nb.id)
                    self.metrics.record_transmitted(is_hello=True)
                    q.append(nb)

        for node in self.network.nodes:
            if node.id not in visited:
                node.gradient_level = float("inf")

    # =========================================================================
    # Start forwarding
    # =========================================================================

    def start_forwarding(self) -> None:
        """Uplink mode: all nodes send data upward + control messages."""
        for node in self.network.nodes:
            if node.is_alive():
                self.env.process(self._node_process(node))

    def start_downlink_forwarding(self) -> None:
        """Downlink mode: control messages build parent sets + next-hop table,
        then sink sends downlink packets."""
        cfg = self.settings
        for node in self.network.nodes:
            if node.is_alive():
                self.env.process(self._ctrl_process(node))
                # Non-sink nodes send heartbeat-style uplink to populate next-hop table
                if not node.is_sink:
                    self.env.process(self._heartbeat_for_table_process(node))
        sink = self.network.sink
        if sink.is_alive():
            self.env.process(self._sink_downlink_process(sink))

    def _heartbeat_for_table_process(self, node: SensorNode):
        """Send periodic uplink packets so sink can build next-hop table."""
        cfg = self.settings
        st  = self._state[node.id]
        # Wait for parent set to be ready
        while st.rank >= 255 or not st.parent_set:
            yield self.env.timeout(BASE_INTERVAL_S)
        while node.is_alive():
            yield self.env.timeout(cfg.HEARTBEAT_INTERVAL_MIN_S)
            self._generate_uplink(node)

    # =========================================================================
    # Per-node processes
    # =========================================================================

    def _node_process(self, node: SensorNode):
        cfg = self.settings
        st  = self._state[node.id]
        yield self.env.timeout(st.start_delay)

        self.env.process(self._ctrl_process(node))
        if not node.is_sink:
            self.env.process(self._uplink_data_process(node))
        yield self.env.timeout(cfg.SIM_DURATION)

    def _ctrl_process(self, node: SensorNode):
        """Periodic control message broadcast with dynamic interval (§3.1.4)."""
        cfg = self.settings
        st  = self._state[node.id]
        while node.is_alive():
            interval = BASE_INTERVAL_S + st.rank * TIME_UNIT_S
            yield self.env.timeout(interval)
            self._purge_parent_set(node)
            self._send_ctrl(node)

    def _uplink_data_process(self, node: SensorNode):
        """Generate uplink DATA packets once rank is valid (§3.2)."""
        cfg = self.settings
        st  = self._state[node.id]
        # Wait until rank is valid (has at least one parent)
        while st.rank >= 255 or not st.parent_set:
            yield self.env.timeout(BASE_INTERVAL_S)

        while node.is_alive():
            yield self.env.timeout(cfg.DATA_INTERVAL)
            for _ in range(cfg.DATA_RATE):
                self._generate_uplink(node)

    def _sink_downlink_process(self, sink: SensorNode):
        """Sink periodically sends downlink packets to all reachable nodes."""
        cfg = self.settings
        # Allow time for next-hop table to be populated from uplink packets
        convergence = cfg.START_DELAY_MAX_S + BASE_INTERVAL_S * 3
        yield self.env.timeout(convergence)

        while sink.is_alive():
            yield self.env.timeout(cfg.DATA_INTERVAL)
            for dest_node in self.network.nodes:
                if dest_node.is_sink or not dest_node.is_alive():
                    continue
                if dest_node.id not in self._nexthop_table:
                    continue   # no route yet
                route = self._build_downlink_route(dest_node.id)
                if route is None:
                    continue
                pkt = ADUPDownlinkPacket(
                    source_id=sink.id,
                    dest_id=dest_node.id,
                    size_bytes=cfg.PACKET_SIZE_BYTES,
                    creation_time=self.env.now,
                    route=route,
                )
                self.metrics.record_created(pkt.id, self.env.now)
                self.env.process(self._forward_downlink(pkt, sink))

    # =========================================================================
    # Parent set management
    # =========================================================================

    def _purge_parent_set(self, node: SensorNode) -> None:
        """Remove stale neighbours (not seen within ROUTE_TIMEOUT_S)."""
        now     = self.env.now
        timeout = self.settings.ROUTE_TIMEOUT_S
        st      = self._state[node.id]
        expired = [
            nb_id for nb_id, ts in st.nb_last_seen.items()
            if (now - ts) > timeout
        ]
        for nb_id in expired:
            st.parent_set.pop(nb_id, None)
            del st.nb_last_seen[nb_id]
        if expired:
            self._recompute_rank(node)

    def _recompute_rank(self, node: SensorNode) -> bool:
        """
        Rank = ROOT_RANK + a × Min_HopRankIncrease  (§3.1.3, Eq. 1)
        a = min(parent_a_value) + 1
        Returns True if rank changed.
        """
        st = self._state[node.id]
        if node.is_sink:
            return False
        if not st.parent_set:
            new_rank = 255
            new_a    = 254
        else:
            # Best parent = lowest rank
            best_parent_rank = min(r for r, _, _ in st.parent_set.values())
            new_a    = (best_parent_rank - ROOT_RANK) // MIN_HOP_RANK_INC + 1
            new_rank = ROOT_RANK + new_a * MIN_HOP_RANK_INC

        if new_rank == st.rank:
            return False
        st.rank    = new_rank
        st.a_value = new_a
        node.gradient_level = float(new_rank)
        return True

    def _update_rssi_and_direction(self, node: SensorNode, nb_id: int,
                                   new_rssi: float) -> None:
        """
        Update parent set RSSI and monitor movement direction (§3.1.1 & §3.1.2).
        Removes parent if node is moving away AND in danger zone.
        """
        st = self._state[node.id]
        nb_state = self._state.get(nb_id)
        if nb_state is None:
            return

        if nb_id in st.parent_set:
            nb_rank, old_rssi, _ = st.parent_set[nb_id]

            # Determine zone (§3.1.2)
            in_safety     = new_rssi >= SAFETY_THRESHOLD_DB
            in_danger     = new_rssi < HYSTERESIS_THRESHOLD_DB
            in_hysteresis = not in_safety and not in_danger

            # Movement direction (§3.1.1)
            if in_hysteresis:
                # Use hysteresis: moving away if new < old + hysteresis
                moving_away = new_rssi < (old_rssi + HYSTERESIS_DB)
            else:
                moving_away = new_rssi < old_rssi

            if in_danger and moving_away:
                # Remove from parent set — link quality too poor
                del st.parent_set[nb_id]
                st.nb_last_seen.pop(nb_id, None)
                self._recompute_rank(node)
            else:
                st.parent_set[nb_id] = (nb_rank, old_rssi, new_rssi)
        else:
            # New potential parent — only add if rank < current node rank
            if nb_state.rank < st.rank:
                st.parent_set[nb_id] = (nb_state.rank, new_rssi, new_rssi)
                self._recompute_rank(node)

    # =========================================================================
    # Control message (beacon)
    # =========================================================================

    def _send_ctrl(self, node: SensorNode) -> None:
        """Broadcast ADUPControlPacket to all neighbours."""
        st = self._state[node.id]
        for nb in node.neighbors:
            ctrl = ADUPControlPacket(
                source_id=node.id,
                dest_id=nb.id,
                creation_time=self.env.now,
                rank=st.rank,
                a_value=st.a_value,
            )
            self.env.process(nb._deliver(node, ctrl, self.channel))
        self.metrics.record_transmitted(is_hello=True)

    # =========================================================================
    # Uplink data generation & forwarding  (§3.2)
    # =========================================================================

    def _get_best_parent(self, node: SensorNode) -> Optional[SensorNode]:
        """Select next-hop: parent with lowest Rank; ties broken by RSSI DESC."""
        st = self._state[node.id]
        if not st.parent_set:
            return None
        best_id = min(
            st.parent_set,
            key=lambda nb_id: (st.parent_set[nb_id][0],   # rank ASC
                               -st.parent_set[nb_id][2])  # new_rssi DESC
        )
        return self.network.get_node_by_id(best_id)

    def _generate_uplink(self, node: SensorNode) -> None:
        best = self._get_best_parent(node)
        if best is None:
            return
        pkt = ADUPUplinkPacket(
            source_id=node.id,
            dest_id=self.network.sink.id,
            size_bytes=self.settings.PACKET_SIZE_BYTES,
            creation_time=self.env.now,
            next_hop_id=best.id,
        )
        self.metrics.record_created(pkt.id, self.env.now)
        self.env.process(self._forward_uplink(pkt, node))

    def _forward_uplink(self, packet: ADUPUplinkPacket, src: SensorNode):
        """Hop-by-hop uplink forwarding. Each hop updates next_hop_id."""
        node = src
        cfg  = self.settings

        while True:
            best = self._get_best_parent(node)
            if best is None:
                packet.mark_dropped(DropReason.NO_NEXT_HOP)
                self.metrics.record_drop("no_next_hop")
                node.packets_dropped_no_route += 1
                packet.drop()
                return

            # Update next_hop_id to reflect forwarder's best parent
            packet.next_hop_id = best.id

            delivered = False
            timeout_s = cfg.SAR_RETRY_TIMEOUT_MS / 1000.0

            for attempt in range(cfg.SAR_RETRY_MAX + 1):
                if attempt > 0:
                    yield self.env.timeout(timeout_s * (cfg.SAR_RETRY_BACKOFF ** attempt))
                yield node.transmit_to(best, packet, self.channel)
                self.metrics.record_transmitted(is_hello=False)
                if packet.drop_reason is None:
                    delivered = True
                    break
                elif packet.drop_reason == DropReason.BUFFER_FULL:
                    break
                else:
                    packet.drop_reason = None

            if not delivered:
                if packet.drop_reason is None:
                    packet.mark_dropped(DropReason.MAX_RETRIES)
                self.metrics.record_drop(
                    packet.drop_reason.value if packet.drop_reason else "other"
                )
                node.packets_dropped_retries += 1
                packet.drop()
                return

            packet.on_forward(node.id)
            if packet.is_ttl_expired():
                packet.mark_dropped(DropReason.TTL_EXPIRED)
                self.metrics.record_drop("ttl_expired")
                packet.drop()
                return

            if best.is_sink:
                self.metrics.record_delivered(
                    packet.id, self.env.now, hop_count=packet.hop_count
                )
                return

            node = best
            yield self.env.timeout(cfg.SAR_INTER_SEGMENT_DELAY_MS / 1000.0)

    # =========================================================================
    # Downlink route building — Algorithm 1  (§3.3)
    # =========================================================================

    def _build_downlink_route(self, dest_id: int) -> Optional[List[int]]:
        """
        Build source route from sink to dest_id using _nexthop_table.

        Algorithm 1:
          Put dest_id in route.
          nexthop = N(dest_id)
          while nexthop != sink_id:
              Put nexthop in route.
              nexthop = N(nexthop)
          Reverse(route)
        Returns ordered list [first_relay, ..., dest_id] or None if no route.
        """
        sink_id = self.network.sink.id
        route   = [dest_id]
        visited: set[int] = {dest_id}
        nexthop = self._nexthop_table.get(dest_id)

        if nexthop is None:
            return None

        while nexthop != sink_id:
            if nexthop in visited:
                return None   # loop detected
            visited.add(nexthop)
            route.append(nexthop)
            nexthop = self._nexthop_table.get(nexthop)
            if nexthop is None:
                return None

        route.reverse()   # now ordered sink→dest
        return route

    # =========================================================================
    # Downlink forwarding  (§3.3, Figure 5)
    # =========================================================================

    def _forward_downlink(self, packet: ADUPDownlinkPacket, src: SensorNode):
        """
        Source-routed downlink forwarding.
        packet.route = [hop_0, hop_1, ..., dest_id]
        packet.route_offset points to current next hop index.
        """
        node = src
        cfg  = self.settings

        while True:
            if packet.is_ttl_expired():
                packet.mark_dropped(DropReason.TTL_EXPIRED)
                self.metrics.record_drop("ttl_expired")
                return

            if packet.route_offset >= len(packet.route):
                packet.mark_dropped(DropReason.NO_NEXT_HOP)
                self.metrics.record_drop("no_next_hop")
                return

            next_id  = packet.route[packet.route_offset]
            next_hop = self.network.get_node_by_id(next_id)
            if next_hop is None or not next_hop.is_alive():
                packet.mark_dropped(DropReason.NO_NEXT_HOP)
                self.metrics.record_drop("no_next_hop")
                return

            delivered = False
            timeout_s = cfg.SAR_RETRY_TIMEOUT_MS / 1000.0

            for attempt in range(cfg.SAR_RETRY_MAX + 1):
                if attempt > 0:
                    yield self.env.timeout(timeout_s * (cfg.SAR_RETRY_BACKOFF ** attempt))
                yield node.transmit_to(next_hop, packet, self.channel)
                self.metrics.record_transmitted(is_hello=False)
                if packet.drop_reason is None:
                    delivered = True
                    break
                elif packet.drop_reason == DropReason.BUFFER_FULL:
                    break
                else:
                    packet.drop_reason = None

            if not delivered:
                if packet.drop_reason is None:
                    packet.mark_dropped(DropReason.MAX_RETRIES)
                self.metrics.record_drop(
                    packet.drop_reason.value if packet.drop_reason else "other"
                )
                return

            packet.on_forward(node.id)
            packet.route_offset += 1   # advance route pointer (Figure 5)

            if next_hop.id == packet.dest_id:
                self.metrics.record_delivered(
                    packet.id, self.env.now, hop_count=packet.hop_count
                )
                return

            node = next_hop
            yield self.env.timeout(cfg.SAR_INTER_SEGMENT_DELAY_MS / 1000.0)

    # =========================================================================
    # RX callback
    # =========================================================================

    def _on_receive(self, node: SensorNode, packet) -> None:
        """
        Dispatch:
        - ADUPControlPacket → update parent set + RSSI
        - ADUPUplinkPacket at sink → update next-hop table
        - ADUPDownlinkPacket → handled inside _forward_downlink (no RX action needed)
        """
        if isinstance(packet, ADUPControlPacket):
            src_id   = packet.source_id
            if src_id == node.id:
                return
            src_node = self.network.get_node_by_id(src_id)
            if src_node is None:
                return

            dist     = node.distance_to(src_node)
            new_rssi = node.calculate_rssi(dist)
            st       = self._state[node.id]

            # Update last-seen timestamp
            st.nb_last_seen[src_id] = self.env.now

            # Update RSSI monitoring + movement direction (§3.1.1 & §3.1.2)
            self._update_rssi_and_direction(node, src_id, new_rssi)

            # Also update sender's rank in our parent set if already present
            if src_id in st.parent_set:
                _, old_rssi, cur_rssi = st.parent_set[src_id]
                st.parent_set[src_id] = (packet.rank, old_rssi, cur_rssi)
                self._recompute_rank(node)

        elif isinstance(packet, ADUPUplinkPacket):
            # Sink learns next-hop: source_id's best parent = next_hop_id
            if node.is_sink:
                self._nexthop_table[packet.source_id] = packet.next_hop_id
                self.metrics.record_delivered(
                    packet.id, self.env.now, hop_count=packet.hop_count
                )
            # Intermediate nodes: update RSSI from sender
            else:
                src_id   = packet.source_id
                src_node = self.network.get_node_by_id(src_id)
                if src_node:
                    dist     = node.distance_to(src_node)
                    new_rssi = node.calculate_rssi(dist)
                    st       = self._state[node.id]
                    st.nb_last_seen[src_id] = self.env.now
                    self._update_rssi_and_direction(node, src_id, new_rssi)
