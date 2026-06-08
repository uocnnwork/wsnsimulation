"""
protocols/flooding.py — Pure Flooding Protocol (Bidirectional, node-centric)

Mechanism:
- UPLINK  (Node → Sink): Pure flooding to all neighbors
- DOWNLINK (Sink → Node): Pure flooding to all neighbors
- Duplicate detection prevents infinite loops

NO gradient, NO routing tables, NO beacons — PURE FLOODING ONLY!
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

import simpy

from models.node import SensorNode
from models.packet import DataPacket, DropReason

if TYPE_CHECKING:
    from models.network import Network
    from models.channel import RicianChannelModel
    from utils.metrics import MetricsCollector


# ===========================================================================
# FloodingNode
# ===========================================================================

class FloodingNode:

    def __init__(self, node: SensorNode, routing: "FloodingRouting"):
        self.node    = node
        self.routing = routing
        self.env: simpy.Environment = node.env
        cfg = node.settings

        self._uplink_dup:    dict[tuple, float] = {}
        self._downlink_dup:  dict[tuple, float] = {}
        self._dup_cache_size = cfg.DUP_CACHE_MAX_SIZE
        self._dup_timeout    = cfg.DUP_CACHE_TIMEOUT_S
        self._start_delay    = random.uniform(0.0, cfg.START_DELAY_MAX_S)

    # -----------------------------------------------------------------------
    # Duplicate cache
    # -----------------------------------------------------------------------

    def _is_dup(self, src_id: int, pkt_id: int) -> bool:
        key = (src_id, pkt_id)
        if key not in self._uplink_dup:
            return False
        if self.env.now - self._uplink_dup[key] > self._dup_timeout:
            del self._uplink_dup[key]
            return False
        return True

    def _remember(self, src_id: int, pkt_id: int) -> None:
        key = (src_id, pkt_id)
        if len(self._uplink_dup) >= self._dup_cache_size:
            del self._uplink_dup[next(iter(self._uplink_dup))]
        self._uplink_dup[key] = self.env.now

    def _is_dl_dup(self, pkt_id: int) -> bool:
        key = (0, pkt_id)
        if key not in self._downlink_dup:
            return False
        if self.env.now - self._downlink_dup[key] > self._dup_timeout:
            del self._downlink_dup[key]
            return False
        return True

    def _remember_dl(self, pkt_id: int) -> None:
        key = (0, pkt_id)
        if len(self._downlink_dup) >= self._dup_cache_size:
            del self._downlink_dup[next(iter(self._downlink_dup))]
        self._downlink_dup[key] = self.env.now    # -----------------------------------------------------------------------
    # Broadcast
    # -----------------------------------------------------------------------

    def _broadcast(self, pkt: DataPacket) -> None:
        routing = self.routing
        for nb in self.node.neighbors:
            if not nb.is_alive():
                continue
            routing.metrics.record_transmitted(is_hello=False)
            # clone() copy path và tx_timestamps thành list độc lập,
            # tránh shared state khi nhiều coroutine chạy song song
            self.env.process(nb._deliver(self.node, pkt.clone(), routing.channel))

    # -----------------------------------------------------------------------
    # Uplink generator
    # -----------------------------------------------------------------------

    def run_uplink_generator(self):
        cfg = self.node.settings
        yield self.env.timeout(self._start_delay)

        while self.node.is_alive():
            yield self.env.timeout(cfg.DATA_INTERVAL)
            if not self.node.neighbors:
                continue

            ttl = getattr(cfg, "FLOODING_TTL", 15)
            pkt = DataPacket(
                source_id=self.node.id,
                dest_id=self.routing.network.sink.id,
                size_bytes=cfg.PACKET_SIZE_BYTES,
                creation_time=self.env.now,
                ttl=ttl,
            )
            self.routing.metrics.record_created(pkt.id, self.env.now)
            self._remember(pkt.source_id, pkt.id)
            pkt.on_forward(self.node.id)
            self._broadcast(pkt)

    # -----------------------------------------------------------------------
    # Downlink generator (sink only)
    # -----------------------------------------------------------------------

    def run_downlink_generator(self):
        """Sink: flood one broadcast packet per interval.
        Each non-sink node rebroadcasts; the intended dest records delivery."""
        cfg = self.node.settings
        yield self.env.timeout(cfg.START_DELAY_MAX_S)

        while self.node.is_alive():
            yield self.env.timeout(cfg.DATA_INTERVAL)
            ttl = getattr(cfg, "FLOODING_TTL", 15)
            # One broadcast packet — dest_id = -1 means "all nodes"
            pkt = DataPacket(
                source_id=self.node.id,
                dest_id=-1,          # broadcast sentinel
                size_bytes=cfg.PACKET_SIZE_BYTES,
                creation_time=self.env.now,
                ttl=ttl,
            )
            self.routing.metrics.record_created(pkt.id, self.env.now)
            self._remember_dl(pkt.id)
            pkt.on_forward(self.node.id)
            self._broadcast(pkt)

    # -----------------------------------------------------------------------
    # RX handler
    # -----------------------------------------------------------------------

    def on_receive(self, pkt: DataPacket) -> None:
        # Chặn: không xử lý gói tin do chính node này sinh ra (loop-back)
        if pkt.source_id == self.node.id:
            return

        # --- DOWNLINK: packet originated from sink ---
        if pkt.source_id == self.routing.network.sink.id and not self.node.is_sink:
            if self._is_dl_dup(pkt.id):
                return
            self._remember_dl(pkt.id)

            # Every non-sink node is a "destination" for broadcast downlink
            pkt.on_forward(self.node.id)
            self.routing.metrics.record_bc_delivered(
                pkt.id, self.node.id, self.env.now
            )

            # Keep rebroadcasting so further nodes can also receive
            if not pkt.is_ttl_expired():
                self._broadcast(pkt)
            else:
                pkt.mark_dropped(DropReason.TTL_EXPIRED)
                self.routing.metrics.record_drop("ttl_expired")
            return

        # --- UPLINK: sensor → sink ---
        src_id = pkt.source_id
        pkt_id = pkt.id

        if self.node.is_sink:
            if self._is_dup(src_id, pkt_id):
                return
            self._remember(src_id, pkt_id)
            pkt.on_forward(self.node.id)
            self.routing.metrics.record_delivered(
                pkt_id, self.env.now, hop_count=pkt.hop_count
            )
            return

        if self._is_dup(src_id, pkt_id):
            return
        self._remember(src_id, pkt_id)

        if pkt.is_ttl_expired():
            pkt.mark_dropped(DropReason.TTL_EXPIRED)
            self.routing.metrics.record_drop("ttl_expired")
            return

        pkt.on_forward(self.node.id)
        self._broadcast(pkt)


# ===========================================================================
# FloodingRouting
# ===========================================================================

class FloodingRouting:

    def __init__(self, network: "Network", channel: "RicianChannelModel",
                 metrics: "MetricsCollector", settings):
        self.network  = network
        self.channel  = channel
        self.metrics  = metrics
        self.settings = settings
        self.env: simpy.Environment = network.env

        self._agents: dict[int, FloodingNode] = {
            node.id: FloodingNode(node, self)
            for node in network.nodes
        }

        for node in network.nodes:
            node._on_receive = self._on_receive

    def run_setup_phase(self) -> None:
        # Flooding thuần túy — không cần khởi tạo topology hay gradient.
        pass

    def start_forwarding(self) -> None:
        for node in self.network.nodes:
            if not node.is_sink and node.is_alive():
                self.env.process(self._agents[node.id].run_uplink_generator())

    def start_downlink_forwarding(self) -> None:
        """Downlink: sink floods a packet to every sensor node."""
        sink = self.network.sink
        if sink.is_alive():
            self.env.process(self._agents[sink.id].run_downlink_generator())

    def _on_receive(self, node: SensorNode, packet) -> None:
        if not isinstance(packet, DataPacket):
            return
        agent = self._agents.get(node.id)
        if agent:
            agent.on_receive(packet)
