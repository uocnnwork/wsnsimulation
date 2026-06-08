"""
protocols/gradient.py — Gradient Routing Protocol

Theo Gradient.md §4:
- 4 loại packet: Beacon, Uplink Data, Heartbeat, Backprop Data
- Forwarding table: {nb_id: (gradient, rssi, last_seen, backprop_set)}
  Sắp xếp: gradient ASC → RSSI DESC → last_seen DESC
- Heartbeat state machine: Fast(5s) → Medium(10s) → Slow(20s) → Maintenance(30m)
  Reset về Fast khi có topology change event
- Backprop learning từ cả Uplink Data và Heartbeat
- last_seen cập nhật khi nhận Beacon hoặc Data
- Downlink: unicast hop-by-hop dựa trên backprop_dest table
"""
from __future__ import annotations

import random
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

import simpy

from models.node import SensorNode
from models.packet import DataPacket, BeaconPacket, DropReason

# nb_id → (gradient, rssi, last_seen, backprop_destinations)
ForwardingEntry = Tuple[int, float, float, Set[int]]
ForwardingTable = Dict[int, ForwardingEntry]

# Heartbeat state machine intervals (§4.3.3)
_HB_STATES: List[float] = [5.0, 10.0, 20.0, 1800.0]  # Fast/Medium/Slow/Maintenance


class GradientRouting:

    def __init__(self, network, channel, metrics, settings):
        self.network  = network
        self.channel  = channel
        self.metrics  = metrics
        self.settings = settings
        self.env: simpy.Environment = network.env

        self._ftable:       Dict[int, ForwardingTable] = {}
        self._gradient:     Dict[int, int]             = {}
        self._hold_down:    Dict[int, float]           = {}
        self._converged_at: Dict[int, float]           = {}

        # Heartbeat state machine per node: index into _HB_STATES
        self._hb_state:     Dict[int, int]   = {}   # 0=Fast … 3=Maintenance
        self._last_hb_time: Dict[int, float] = {}

        for node in network.nodes:
            g = 0 if node.is_sink else settings.GRADIENT_INFINITY
            self._ftable[node.id]        = {}
            self._gradient[node.id]      = g
            self._hold_down[node.id]     = 0.0
            self._converged_at[node.id]  = -1.0
            self._hb_state[node.id]      = 0       # start at Fast
            self._last_hb_time[node.id]  = 0.0

        for node in network.nodes:
            node._on_receive = self._on_receive

    # =========================================================================
    # Helpers — heartbeat state machine
    # =========================================================================

    def _hb_interval(self, node_id: int) -> float:
        return _HB_STATES[self._hb_state[node_id]]

    def _hb_reset_fast(self, node_id: int) -> None:
        """Topology change event → reset to Fast state (§4.3.3)."""
        self._hb_state[node_id] = 0

    def _hb_advance(self, node_id: int) -> None:
        """After sending heartbeat, advance to next slower state."""
        self._hb_state[node_id] = min(
            self._hb_state[node_id] + 1, len(_HB_STATES) - 1
        )

    # =========================================================================
    # Setup Phase — BFS warm-start
    # =========================================================================

    def run_setup_phase(self) -> None:
        sink    = self.network.sink
        visited: set[int] = {sink.id}
        q: deque[SensorNode] = deque([sink])

        while q:
            current = q.popleft()
            g_current = self._gradient[current.id]
            for nb in current.neighbors:
                if nb.id not in visited:
                    dist = current.distance_to(nb)
                    rssi = current.calculate_rssi(dist)
                    new_g = g_current + 1
                    self._ftable[nb.id][current.id] = (g_current, rssi, 0.0, set())
                    self._gradient[nb.id] = new_g
                    nb.gradient_level = float(new_g)
                    visited.add(nb.id)
                    self.metrics.record_transmitted(is_hello=True)
                    q.append(nb)

        for node in self.network.nodes:
            if node.id not in visited:
                node.gradient_level = float("inf")

    # =========================================================================
    # Forwarding Phase
    # =========================================================================

    def start_forwarding(self) -> None:
        for node in self.network.nodes:
            if node.is_alive():
                self.env.process(self._node_process(node))

    def start_downlink_forwarding(self) -> None:
        """Downlink: beacons + heartbeats build backprop table,
        then sink sends Backprop Data packets."""
        for node in self.network.nodes:
            if node.is_alive():
                self.env.process(self._beacon_process(node))
                if not node.is_sink:
                    self.env.process(self._heartbeat_process(node))
        sink = self.network.sink
        if sink.is_alive():
            self.env.process(self._sink_downlink_process(sink))

    def _node_process(self, node: SensorNode):
        cfg = self.settings
        yield self.env.timeout(random.uniform(0.0, cfg.START_DELAY_MAX_S))
        self.env.process(self._beacon_process(node))
        if not node.is_sink:
            self.env.process(self._data_process(node))
            self.env.process(self._heartbeat_process(node))
        yield self.env.timeout(cfg.SIM_DURATION)

    # =========================================================================
    # Sub-processes
    # =========================================================================

    def _beacon_process(self, node: SensorNode):
        """Periodic beacon + triggered update when gradient changes (§4.1, §4.3.1)."""
        cfg = self.settings
        while node.is_alive():
            yield self.env.timeout(cfg.BEACON_PERIOD_S)
            self._purge_ftable(node)
            changed = self._recompute_gradient(node)
            self._send_beacon(node)
            if changed:
                # Triggered update: gradient changed → reset heartbeat to Fast
                self._hb_reset_fast(node.id)

    def _data_process(self, node: SensorNode):
        """Periodic DATA — only after gradient converges (§4.3.1)."""
        cfg = self.settings
        while self._gradient[node.id] >= cfg.GRADIENT_INFINITY:
            yield self.env.timeout(cfg.BEACON_PERIOD_S)
        self._converged_at[node.id] = self.env.now

        while node.is_alive():
            yield self.env.timeout(cfg.DATA_INTERVAL)
            for _ in range(cfg.DATA_RATE):
                self._generate_data(node)

    def _heartbeat_process(self, node: SensorNode):
        """Heartbeat state machine: Fast→Medium→Slow→Maintenance (§4.3.3).
        Checks every Fast interval; sends only when elapsed >= current interval."""
        while node.is_alive():
            yield self.env.timeout(_HB_STATES[0])   # poll at fastest rate
            self._maybe_send_heartbeat(node)

    def _sink_downlink_process(self, sink: SensorNode):
        """Sink sends Backprop Data packets once backprop routes are learned (§4.1, §4.3.2)."""
        cfg = self.settings
        # Allow beacons + heartbeats to populate backprop table
        convergence_wait = cfg.START_DELAY_MAX_S + cfg.BEACON_PERIOD_S * 2
        yield self.env.timeout(convergence_wait)

        while sink.is_alive():
            yield self.env.timeout(cfg.DATA_INTERVAL)
            for node in self.network.nodes:
                if node.is_sink or not node.is_alive():
                    continue
                # Only send if backprop route exists for this destination
                has_route = any(
                    node.id in bset or node.id == nb_id
                    for nb_id, (_, _, _, bset) in self._ftable[sink.id].items()
                )
                if not has_route:
                    continue
                pkt = DataPacket(
                    source_id=sink.id,
                    dest_id=node.id,
                    size_bytes=cfg.PACKET_SIZE_BYTES,
                    creation_time=self.env.now,
                )
                self.metrics.record_created(pkt.id, self.env.now)
                self.env.process(self._forward_downlink(pkt, sink))

    # =========================================================================
    # Forwarding table management
    # =========================================================================

    def _purge_ftable(self, node: SensorNode) -> None:
        """Remove stale entries; reset heartbeat to Fast if any expire (§4.3.1)."""
        now     = self.env.now
        timeout = self.settings.ROUTE_TIMEOUT_S
        expired = [
            nb_id for nb_id, (_, _, last_seen, _) in self._ftable[node.id].items()
            if (now - last_seen) > timeout
        ]
        for nb_id in expired:
            del self._ftable[node.id][nb_id]
        if expired:
            self._hb_reset_fast(node.id)   # topology change → Fast state

    def _recompute_gradient(self, node: SensorNode) -> bool:
        """Gradient = min(neighbour_gradient) + 1 (§4.3.1)."""
        cfg = self.settings
        if node.is_sink:
            if self._gradient[node.id] != 0:
                self._gradient[node.id] = 0
                return True
            return False

        now = self.env.now
        if now < self._hold_down[node.id]:
            return False

        if not self._ftable[node.id]:
            new_g = cfg.GRADIENT_INFINITY
        else:
            min_nb_g = min(g for g, _, _, _ in self._ftable[node.id].values())
            new_g = cfg.GRADIENT_INFINITY if min_nb_g >= 254 else (min_nb_g + 1)

        if new_g > self._gradient[node.id] and self._gradient[node.id] != cfg.GRADIENT_INFINITY:
            new_g = cfg.GRADIENT_INFINITY
            self._hold_down[node.id] = now + cfg.HOLD_DOWN_TIME_S

        if new_g == self._gradient[node.id]:
            return False

        self._gradient[node.id] = new_g
        node.gradient_level = float(new_g)
        return True

    def _get_sorted_nexthops(self, node: SensorNode) -> list[tuple[int, int, float, float]]:
        """
        Sort by: gradient ASC → RSSI DESC → last_seen DESC (§4.2 Index sorting).
        Only include candidates with gradient < current node's gradient.
        Returns list of (nb_id, gradient, rssi, last_seen).
        """
        my_g = self._gradient[node.id]
        candidates = [
            (nb_id, g, rssi, last_seen)
            for nb_id, (g, rssi, last_seen, _) in self._ftable[node.id].items()
            if g < my_g
        ]
        candidates.sort(key=lambda x: (x[1], -x[2], -x[3]))
        return candidates

    def _get_best_parent(self, node: SensorNode) -> Optional[int]:
        """Return nb_id of best parent (Index 1 in sorted table), or None."""
        nexthops = self._get_sorted_nexthops(node)
        return nexthops[0][0] if nexthops else None

    # =========================================================================
    # Backprop learning (§4.3.2)
    # =========================================================================

    def _add_backprop(self, node: SensorNode,
                      src_unicast_id: int, backprop_dest_id: int) -> None:
        """
        Learn that backprop_dest_id is reachable via src_unicast_id.
        Remove from all other neighbours (exclusive association).
        """
        for nb_id, (g, rssi, last_seen, bset) in list(self._ftable[node.id].items()):
            if nb_id == src_unicast_id:
                bset.add(backprop_dest_id)
            else:
                bset.discard(backprop_dest_id)
            self._ftable[node.id][nb_id] = (g, rssi, last_seen, bset)

    def _update_last_seen(self, node: SensorNode, nb_id: int) -> None:
        """Update last_seen for a neighbour on receiving any packet from them (§4.2)."""
        if nb_id in self._ftable[node.id]:
            g, rssi, _, bset = self._ftable[node.id][nb_id]
            self._ftable[node.id][nb_id] = (g, rssi, self.env.now, bset)

    # =========================================================================
    # Beacon (§4.1)
    # =========================================================================

    def _send_beacon(self, node: SensorNode) -> None:
        """Broadcast Gradient Beacon to all neighbours."""
        for nb in node.neighbors:
            beacon = BeaconPacket(
                source_id=node.id,
                dest_id=nb.id,
                size_bytes=4,
                creation_time=self.env.now,
                gradient_level=self._gradient[node.id],
            )
            self.env.process(nb._deliver(node, beacon, self.channel))
        self.metrics.record_transmitted(is_hello=True)

    # =========================================================================
    # Heartbeat (§4.1, §4.3.3)
    # =========================================================================

    def _maybe_send_heartbeat(self, node: SensorNode) -> None:
        """Send heartbeat if current state interval has elapsed."""
        now      = self.env.now
        interval = self._hb_interval(node.id)
        if (now - self._last_hb_time[node.id]) < interval:
            return
        nexthops = self._get_sorted_nexthops(node)
        if not nexthops:
            return
        # Heartbeat payload = 0xFFFF (§4.1)
        hb = DataPacket(
            source_id=node.id,
            dest_id=self.network.sink.id,
            size_bytes=4,
            creation_time=now,
            payload=0xFFFF,
        )
        self.env.process(self._forward(hb, node, is_heartbeat=True))
        self._last_hb_time[node.id] = now
        self._hb_advance(node.id)   # move to next slower state

    # =========================================================================
    # DATA generation (§4.1 — Uplink Data)
    # =========================================================================

    def _generate_data(self, node: SensorNode) -> None:
        pkt = DataPacket(
            source_id=node.id,
            dest_id=self.network.sink.id,
            size_bytes=self.settings.PACKET_SIZE_BYTES,
            creation_time=self.env.now,
        )
        self.metrics.record_created(pkt.id, self.env.now)
        self.env.process(self._forward(pkt, node))

    # =========================================================================
    # Uplink forwarding (§4.1, §4.3.2)
    # =========================================================================

    def _forward(self, packet: DataPacket, src: SensorNode,
                 is_heartbeat: bool = False):
        """Hop-by-hop uplink forwarding toward sink."""
        node = src
        cfg  = self.settings

        while True:
            nexthops = self._get_sorted_nexthops(node)
            if not nexthops:
                if not is_heartbeat:
                    packet.mark_dropped(DropReason.NO_NEXT_HOP)
                    self.metrics.record_drop("no_next_hop")
                    node.packets_dropped_no_route += 1
                    packet.drop()
                return

            nb_id = nexthops[0][0]
            next_hop = self.network.get_node_by_id(nb_id)
            if next_hop is None or not next_hop.is_alive():
                if not is_heartbeat:
                    packet.mark_dropped(DropReason.NO_NEXT_HOP)
                    self.metrics.record_drop("no_next_hop")
                    node.packets_dropped_no_route += 1
                    packet.drop()
                return

            # Backprop learning at next_hop: learn source_id came via node (§4.3.2)
            # Heartbeats also build backprop routes (§4.1)
            self._add_backprop(next_hop, node.id, packet.source_id)

            delivered = False
            timeout_s = cfg.SAR_RETRY_TIMEOUT_MS / 1000.0

            for attempt in range(cfg.SAR_RETRY_MAX + 1):
                if attempt > 0:
                    yield self.env.timeout(timeout_s * (cfg.SAR_RETRY_BACKOFF ** attempt))
                yield node.transmit_to(next_hop, packet, self.channel)
                if not is_heartbeat:
                    self.metrics.record_transmitted(is_hello=False)
                if packet.drop_reason is None:
                    delivered = True
                    break
                elif packet.drop_reason == DropReason.BUFFER_FULL:
                    break
                else:
                    packet.drop_reason = None

            if not delivered:
                if not is_heartbeat:
                    if packet.drop_reason is None:
                        packet.mark_dropped(DropReason.MAX_RETRIES)
                    self.metrics.record_drop(
                        packet.drop_reason.value if packet.drop_reason else "other"
                    )
                    node.packets_dropped_retries += 1
                    packet.drop()
                return

            if not is_heartbeat:
                packet.on_forward(node.id)
                if packet.is_ttl_expired():
                    packet.mark_dropped(DropReason.TTL_EXPIRED)
                    self.metrics.record_drop("ttl_expired")
                    packet.drop()
                    return

            if next_hop.is_sink:
                if not is_heartbeat:
                    self.metrics.record_delivered(
                        packet.id, self.env.now, hop_count=packet.hop_count
                    )
                return

            node = next_hop
            yield self.env.timeout(cfg.SAR_INTER_SEGMENT_DELAY_MS / 1000.0)

    # =========================================================================
    # Downlink forwarding (§4.1 — Backprop Data, §4.3.2)
    # =========================================================================

    def _get_downlink_nexthop(self, node: SensorNode, dest_id: int) -> Optional[SensorNode]:
        """
        Find next-hop toward dest_id using backprop_dest table (§4.2, §4.3.2):
        - nb_id == dest_id  (direct neighbour)
        - dest_id in backprop_set of nb_id
        """
        for nb_id, (_, _, _, bset) in self._ftable[node.id].items():
            if dest_id == nb_id or dest_id in bset:
                nb = self.network.get_node_by_id(nb_id)
                if nb and nb.is_alive():
                    return nb
        return None

    def _forward_downlink(self, packet: DataPacket, src: SensorNode):
        """Hop-by-hop downlink forwarding: sink → destination node (§4.1, §4.3.2)."""
        node = src
        cfg  = self.settings
        visited: set[int] = {node.id}

        while True:
            if packet.is_ttl_expired():
                packet.mark_dropped(DropReason.TTL_EXPIRED)
                self.metrics.record_drop("ttl_expired")
                return

            next_hop = self._get_downlink_nexthop(node, packet.dest_id)
            if next_hop is None or next_hop.id in visited:
                packet.mark_dropped(DropReason.NO_NEXT_HOP)
                self.metrics.record_drop("no_next_hop")
                return

            visited.add(next_hop.id)
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
        if isinstance(packet, BeaconPacket):
            # Update forwarding table on beacon receipt (§4.1)
            src_id   = packet.source_id
            src_node = self.network.get_node_by_id(src_id)
            if src_node is None:
                return
            dist = node.distance_to(src_node)
            rssi = node.calculate_rssi(dist)
            existing = self._ftable[node.id].get(src_id)
            bset: Set[int] = existing[3] if existing else set()
            old_g = existing[0] if existing else None
            self._ftable[node.id][src_id] = (
                packet.gradient_level, rssi, self.env.now, bset
            )
            # Topology change: neighbour gradient changed → reset heartbeat (§4.3.3)
            if old_g is not None and old_g != packet.gradient_level:
                self._hb_reset_fast(node.id)

        elif isinstance(packet, DataPacket):
            # Update last_seen for sender on receiving any data packet (§4.2)
            src_id = packet.source_id
            self._update_last_seen(node, src_id)
            # Heartbeat: payload 0xFFFF — only update routing, don't deliver (§4.1)
            if packet.payload == 0xFFFF:
                self._add_backprop(node, src_id, packet.source_id)
