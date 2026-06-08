"""
utils/metrics.py — Extended MetricsCollector for SimPy-based WSN simulation.
Tracks PDR, NTL, energy, drop reasons, hop stats.
"""
from __future__ import annotations


class MetricsCollector:

    def __init__(self):
        # Packet lifecycle
        self._created:    dict[int, float] = {}  # pkt_id → creation_time
        self._delivered:  dict[int, float] = {}  # pkt_id → delivery_time
        self._hop_counts: dict[int, int]   = {}  # pkt_id → hop_count on delivery

        # Downlink broadcast tracking (flooding-specific, không ảnh hưởng PDR chính)
        # (pkt_id, node_id) → delivery_time — đếm số node duy nhất nhận được mỗi gói
        self._bc_deliveries: dict[tuple, float] = {}

        # Transmission counter (all attempts: HELLO + DATA, success + fail)
        self._total_transmissions: int = 0

        # Drop counters by reason
        self._drops: dict[str, int] = {
            "rssi_too_low":  0,
            "buffer_full":   0,
            "no_next_hop":   0,
            "max_retries":   0,
            "duplicate":     0,
            "ttl_expired":   0,
            "other":         0,
        }

        # Energy (mJ) — accumulated from all nodes
        self._total_energy_consumed: float = 0.0

        # HELLO transmissions (setup phase)
        self._hello_transmissions: int = 0

    # -------------------------------------------------------------------------
    # Recording API
    # -------------------------------------------------------------------------

    def record_created(self, packet_id: int, creation_time: float) -> None:
        self._created[packet_id] = creation_time

    def record_transmitted(self, is_hello: bool = False) -> None:
        self._total_transmissions += 1
        if is_hello:
            self._hello_transmissions += 1

    def record_delivered(self, packet_id: int, delivery_time: float,
                         hop_count: int = 0) -> None:
        self._delivered[packet_id] = delivery_time
        self._hop_counts[packet_id] = hop_count

    def record_bc_delivered(self, packet_id: int, node_id: int,
                             delivery_time: float) -> None:
        """Broadcast downlink delivery — mỗi (pkt_id, node_id) chỉ tính 1 lần.
        Dùng riêng cho flooding downlink, không ảnh hưởng get_pdr()."""
        key = (packet_id, node_id)
        if key not in self._bc_deliveries:
            self._bc_deliveries[key] = delivery_time

    def record_drop(self, reason: str) -> None:
        key = reason if reason in self._drops else "other"
        self._drops[key] += 1

    def record_energy(self, mj: float) -> None:
        self._total_energy_consumed += mj

    # -------------------------------------------------------------------------
    # KPI getters
    # -------------------------------------------------------------------------

    def get_pdr(self) -> float:
        """PDR (%) = delivered / created × 100."""
        if not self._created:
            return 0.0
        return len(self._delivered) / len(self._created) * 100.0

    def get_pdr_broadcast(self, num_non_sink_nodes: int) -> float:
        """PDR cho broadcast downlink: unique (pkt_id, node_id) nhận được
        chia cho (số gói tạo ra × số non-sink node).
        Chỉ có ý nghĩa khi dùng với flooding downlink."""
        unique_pkts = len({pkt_id for pkt_id, _ in self._bc_deliveries})
        n_created   = len(self._created)
        total_expected = n_created * num_non_sink_nodes
        if total_expected == 0:
            return 0.0
        return len(self._bc_deliveries) / total_expected * 100.0

    def get_ntl(self) -> int:
        """Total transmission attempts (HELLO + DATA)."""
        return self._total_transmissions

    def get_data_ntl(self) -> int:
        """DATA-only transmission attempts."""
        return self._total_transmissions - self._hello_transmissions

    def get_avg_rtt(self) -> float:
        """Mean end-to-end latency (seconds) of successfully delivered packets."""
        if not self._delivered:
            return 0.0
        rtts = [
            self._delivered[pid] - self._created[pid]
            for pid in self._delivered if pid in self._created
        ]
        return sum(rtts) / len(rtts) if rtts else 0.0

    def get_rtt_distribution(self) -> list[float]:
        """All individual latency values (seconds) — for CDF / histogram."""
        return [
            self._delivered[pid] - self._created[pid]
            for pid in self._delivered if pid in self._created
        ]

    def get_avg_hop_count(self) -> float:
        """Mean hop count of delivered packets."""
        if not self._hop_counts:
            return 0.0
        return sum(self._hop_counts.values()) / len(self._hop_counts)

    def get_drop_counts(self) -> dict[str, int]:
        return dict(self._drops)

    def get_total_drops(self) -> int:
        return sum(self._drops.values())

    def get_total_energy(self) -> float:
        return self._total_energy_consumed

    def get_energy_per_delivered(self) -> float:
        n = len(self._delivered)
        if n == 0:
            return 0.0
        return self._total_energy_consumed / n

    # -------------------------------------------------------------------------
    # Raw data export
    # -------------------------------------------------------------------------

    def get_raw_data(self) -> dict:
        return {
            "created":              dict(self._created),
            "delivered":            dict(self._delivered),
            "hop_counts":           dict(self._hop_counts),
            "bc_deliveries_count":  len(self._bc_deliveries),
            "total_transmissions":  self._total_transmissions,
            "hello_transmissions":  self._hello_transmissions,
            "drops":                dict(self._drops),
            "total_energy_mj":      self._total_energy_consumed,
        }
