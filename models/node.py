"""
models/node.py — SensorNode with SimPy event loop, energy model,
byte-based RX buffer, duplicate detection, and per-node metrics.
Tuned for nRF54L15 BLE Mesh Indoor.
"""
from __future__ import annotations

import math
import random
from collections import deque
from typing import TYPE_CHECKING

import simpy

from models.packet import DataPacket, BeaconPacket, PacketType, DropReason

if TYPE_CHECKING:
    pass


class SensorNode:
    def __init__(
        self,
        node_id:        int,
        x:              float,
        y:              float,
        env:            simpy.Environment,
        settings,
        is_sink:        bool = False,
    ):
        # --- Identity & position ---
        self.id:       int   = node_id
        self.x:        float = x
        self.y:        float = y
        self.env:      simpy.Environment = env
        self.settings  = settings
        self.is_sink:  bool  = is_sink

        # --- Gradient routing ---
        self.gradient_level: float = 0.0 if is_sink else math.inf
        self.neighbors: list[SensorNode] = []

        # --- Energy (mJ) ---
        self.energy:          float = settings.INITIAL_ENERGY
        self.energy_consumed: float = 0.0

        # --- RX buffer (byte-based SimPy Store) ---
        cap = (settings.RX_BUFFER_BYTES_GATEWAY
               if is_sink else settings.RX_BUFFER_BYTES_NODE)
        self.inbox_byte_capacity: int = cap
        self.inbox_byte_usage:    int = 0
        self.inbox: simpy.Store = simpy.Store(env)

        # --- Per-node packet metrics ---
        self.packets_sent:              int = 0
        self.packets_received:          int = 0
        self.packets_dropped_rssi:      int = 0
        self.packets_dropped_buffer:    int = 0
        self.packets_dropped_no_route:  int = 0
        self.packets_dropped_retries:   int = 0
        self.bytes_transmitted:         int = 0

        # --- Channel activity (for CCA) ---
        self.last_tx_time: float = -999.0
        self.last_rx_time: float = -999.0

        # --- Duplicate detection cache: (src_id, pkt_id) → timestamp ---
        self._dup_cache: dict[tuple, float] = {}

        # --- Protocol process handle (set by routing layer) ---
        self._rx_process = env.process(self._rx_loop())

    # =========================================================================
    # Geometry & RF helpers
    # =========================================================================

    def distance_to(self, other: SensorNode) -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def calculate_rssi(self, distance: float) -> float:
        """Log-distance path-loss model (used for neighbor discovery only)."""
        if distance <= 1.0:
            return self.settings.RSSI_AT_1M
        return (self.settings.RSSI_AT_1M
                - 10.0 * self.settings.PATH_LOSS_EXPONENT
                * math.log10(distance))

    def can_communicate(self, other: SensorNode) -> bool:
        """True if RSSI at other's distance exceeds receiver sensitivity."""
        rssi = self.calculate_rssi(self.distance_to(other))
        return rssi >= self.settings.RECEIVER_SENSITIVITY_DBM

    # =========================================================================
    # Energy
    # =========================================================================

    def consume_energy(self, mj: float) -> None:
        self.energy = max(0.0, self.energy - mj)
        self.energy_consumed += mj

    def is_alive(self) -> bool:
        return self.energy > 0.0

    # =========================================================================
    # Duplicate detection
    # =========================================================================

    def is_duplicate(self, src_id: int, pkt_id: int) -> bool:
        key = (src_id, pkt_id)
        if key not in self._dup_cache:
            return False
        age = self.env.now - self._dup_cache[key]
        if age > self.settings.DUP_CACHE_TIMEOUT_S:
            del self._dup_cache[key]
            return False
        return True

    def remember_packet(self, src_id: int, pkt_id: int) -> None:
        key = (src_id, pkt_id)
        if len(self._dup_cache) >= self.settings.DUP_CACHE_MAX_SIZE:
            oldest = next(iter(self._dup_cache))
            del self._dup_cache[oldest]
        self._dup_cache[key] = self.env.now

    # =========================================================================
    # CCA — Clear Channel Assessment
    # =========================================================================

    def _channel_clear(self) -> bool:
        min_gap = self.settings.CCA_MIN_SPACING_MS / 1000.0
        now = self.env.now
        return (now - self.last_tx_time) >= min_gap and \
               (now - self.last_rx_time) >= min_gap

    # =========================================================================
    # TX air-time helper
    # =========================================================================

    def _tx_air_time(self, size_bytes: int) -> float:
        """nRF54L15 @ BLE 1 Mbps: (preamble + payload) * 8 µs + stack overhead."""
        air_us = (10 + size_bytes) * 8
        overhead_us = 100
        total_ms = (air_us + overhead_us) / 1000.0
        return max(0.15, min(0.8, total_ms)) / 1000.0  # seconds

    def _rx_proc_delay(self, size_bytes: int) -> float:
        if size_bytes <= 10:
            return 0.0002
        if size_bytes <= 50:
            return 0.0004
        return 0.0008

    # =========================================================================
    # Low-level deliver (SimPy generator — called by transmitter)
    # =========================================================================

    def _deliver(self, sender: SensorNode, packet,
                 channel, metrics=None) -> simpy.events.Event:
        """Full TX pipeline: jitter → CCA → air-time → RSSI loss → buffer.

        metrics: nếu được truyền vào, gọi record_transmitted sau air-time
                 (dùng cho flooding — Gradient/ADUP tự gọi ở routing layer).
        """

        # 1. Random TX jitter (collision avoidance)
        jitter = random.uniform(
            self.settings.SAR_TX_JITTER_MIN_MS,
            self.settings.SAR_TX_JITTER_MAX_MS,
        ) / 1000.0
        yield self.env.timeout(jitter)

        # 2. CCA with retries
        for _ in range(self.settings.CCA_MAX_RETRIES):
            if sender._channel_clear():
                break
            yield self.env.timeout(self.settings.CCA_MIN_SPACING_MS / 1000.0)

        # 3. Air-time
        air = sender._tx_air_time(packet.size_bytes)
        yield self.env.timeout(air)
        sender.last_tx_time = self.env.now
        sender.consume_energy(self.settings.ENERGY_PER_TX)
        sender.packets_sent += 1
        sender.bytes_transmitted += packet.size_bytes
        packet.tx_timestamps.append(self.env.now)

        # Đếm TX attempt tại đây — sau khi chiếm kênh thực sự
        if metrics is not None:
            metrics.record_transmitted(is_hello=False)

        # 4. Rician LUT channel decision — đếm concurrent TX trong vùng lân cận
        dist = sender.distance_to(self)
        # Đếm số neighbor của receiver đang transmit đồng thời
        # (trong window CCA_MIN_SPACING_MS) — đây là số interferer thực tế
        now = self.env.now
        cca_window = self.settings.CCA_MIN_SPACING_MS / 1000.0
        concurrent = sum(
            1 for nb in self.neighbors
            if nb.id != sender.id and (now - nb.last_tx_time) < cca_window
        ) + 1  # +1 cho sender hiện tại
        success = channel.transmit(dist, concurrent_tx=concurrent)
        if not success:
            self.packets_dropped_rssi += 1
            if isinstance(packet, (DataPacket, BeaconPacket)):
                packet.mark_dropped(DropReason.RSSI_TOO_LOW)
            return

        # 5. RX buffer check (beacons are small — always fits, skip check)
        if isinstance(packet, DataPacket):
            pkt_size = packet.size_bytes + 8
            if self.inbox_byte_usage + pkt_size > self.inbox_byte_capacity:
                self.packets_dropped_buffer += 1
                packet.mark_dropped(DropReason.BUFFER_FULL)
                return
            self.inbox_byte_usage += pkt_size

        # 6. Enqueue into RX buffer
        self.last_rx_time = self.env.now
        self.consume_energy(self.settings.ENERGY_PER_RX)
        yield self.inbox.put(packet)

    # =========================================================================
    # Public transmit API (used by routing layer)
    # =========================================================================

    def transmit_to(self, recipient: SensorNode, packet,
                    channel) -> simpy.events.Event:
        """Start a delivery process toward recipient. Returns the process."""
        return self.env.process(recipient._deliver(self, packet, channel))

    # =========================================================================
    # RX loop — dequeues packets and dispatches to protocol handler
    # =========================================================================

    def _rx_loop(self):
        while True:
            pkt = yield self.inbox.get()
            delay = self._rx_proc_delay(pkt.size_bytes)
            yield self.env.timeout(delay)
            if isinstance(pkt, DataPacket):
                self.inbox_byte_usage -= (pkt.size_bytes + 8)
                if self.inbox_byte_usage < 0:
                    self.inbox_byte_usage = 0
            self.packets_received += 1
            if self._on_receive:
                self._on_receive(self, pkt)

    # Protocol callback — set by routing layer after construction
    _on_receive = None   # type: ignore[assignment]

    # =========================================================================
    # Legacy compatibility shim (used by Network topology builder)
    # =========================================================================

    def enqueue(self, packet: DataPacket) -> None:
        """Compatibility shim — not used in SimPy mode."""
        pass

    def dequeue(self) -> Packet | None:
        return None
