"""
models/packet.py — Packet hierarchy for WSN Gradient Simulator.

Packet types:
  DataPacket   — sensor DATA with path recording, TTL, hop counter
  BeaconPacket — gradient setup beacon
  DSDVPacket   — routing table exchange for DSDV algorithm (future use)
"""
from __future__ import annotations

import itertools
from enum import Enum
from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# SAR segmentation constant (BLE Mesh upper transport layer)
# ---------------------------------------------------------------------------
SAR_SEGMENT_PAYLOAD_BYTES: int = 12  # max upper-transport bytes per segment


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PacketType(Enum):
    DATA              = "DATA"
    BEACON            = "BEACON"
    HELLO             = "HELLO"           # backward compatibility alias
    DSDV_ROUTING_INFO = "DSDV_ROUTING_INFO"


class DropReason(Enum):
    RSSI_TOO_LOW = "rssi_too_low"
    BUFFER_FULL  = "buffer_full"
    NO_NEXT_HOP  = "no_next_hop"
    MAX_RETRIES  = "max_retries"
    DUPLICATE    = "duplicate"
    TTL_EXPIRED  = "ttl_expired"
    OTHER        = "other"


# ---------------------------------------------------------------------------
# Base Packet
# ---------------------------------------------------------------------------

class Packet:
    _id_counter = itertools.count(1)

    def __init__(
        self,
        source_id:     int,
        dest_id:       int,
        size_bytes:    int,
        ptype:         PacketType,
        creation_time: float,
    ):
        self.id:            int                  = next(Packet._id_counter)
        self.source_id:     int                  = source_id
        self.dest_id:       int                  = dest_id
        self.size_bytes:    int                  = int(size_bytes)
        self.ptype:         PacketType           = ptype
        self.creation_time: float                = creation_time
        self.hop_count:     int                  = 0
        self.last_hop:      Optional[int]        = None
        self.drop_reason:   Optional[DropReason] = None
        self.tx_timestamps: list[float]          = []

    def num_segments(self,
                     segment_payload_bytes: int = SAR_SEGMENT_PAYLOAD_BYTES) -> int:
        seg = max(1, segment_payload_bytes)
        return max(1, (self.size_bytes + seg - 1) // seg)

    def increment_hop(self) -> None:
        self.hop_count += 1

    def mark_dropped(self, reason: DropReason) -> None:
        self.drop_reason = reason

    def drop(self) -> None:
        pass


# ---------------------------------------------------------------------------
# DATA packet
# ---------------------------------------------------------------------------

class DataPacket(Packet):
    """Sensor data packet with path recording and TTL."""

    DEFAULT_TTL: int = 100

    def __init__(
        self,
        source_id:     int,
        dest_id:       int,
        size_bytes:    int,
        creation_time: float,
        payload=None,
        ttl:           int = DEFAULT_TTL,
    ):
        super().__init__(source_id, dest_id, size_bytes,
                         PacketType.DATA, creation_time)
        self.ttl:     int       = ttl
        self.payload            = payload
        self.path:    list[int] = [source_id]

    def on_forward(self, forwarder_id: int) -> None:
        self.ttl       -= 1
        self.hop_count += 1
        self.last_hop   = forwarder_id
        self.path.append(forwarder_id)

    def clone(self) -> "DataPacket":
        """Bản sao độc lập cho flooding — nhanh hơn deepcopy."""
        obj = object.__new__(DataPacket)
        obj.id            = self.id
        obj.source_id     = self.source_id
        obj.dest_id       = self.dest_id
        obj.size_bytes    = self.size_bytes
        obj.ptype         = self.ptype
        obj.creation_time = self.creation_time
        obj.hop_count     = self.hop_count
        obj.last_hop      = self.last_hop
        obj.drop_reason   = self.drop_reason
        obj.tx_timestamps = list(self.tx_timestamps)
        obj.ttl           = self.ttl
        obj.payload       = self.payload
        obj.path          = list(self.path)
        return obj

    def is_ttl_expired(self) -> bool:
        return self.ttl <= 0

    def drop(self) -> None:
        self.path.append(-1)


# ---------------------------------------------------------------------------
# BEACON packet  (gradient setup)
# ---------------------------------------------------------------------------

class BeaconPacket(Packet):
    """Broadcast beacon carrying gradient level from Sink outward."""

    def __init__(
        self,
        source_id:      int,
        dest_id:        int,
        size_bytes:     int,
        creation_time:  float,
        gradient_level: int,
    ):
        super().__init__(source_id, dest_id, size_bytes,
                         PacketType.BEACON, creation_time)
        self.gradient_level: int = gradient_level


# ---------------------------------------------------------------------------
# DSDV routing-table packet  (future DSDV algorithm)
# ---------------------------------------------------------------------------

class DSDVPacket(Packet):
    """Routing-table exchange packet for DSDV protocol."""

    def __init__(
        self,
        source_id:     int,
        dest_id:       int,
        size_bytes:    int,
        creation_time: float,
        payload: Optional[Dict[int, Tuple[int, float, int]]] = None,
    ):
        super().__init__(source_id, dest_id, size_bytes,
                         PacketType.DSDV_ROUTING_INFO, creation_time)
        self.payload: Dict[int, Tuple[int, float, int]] = payload or {}
