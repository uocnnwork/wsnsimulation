"""
models/network.py — Network topology builder (Random / Grid / Star / Tree).
Nodes are constructed with a SimPy environment for event-driven simulation.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np
import simpy

from models.node import SensorNode


class Network:
    VALID_TOPOLOGIES = {"Random", "Grid", "Star", "Tree"}

    def __init__(self, env: simpy.Environment, settings):
        self.env      = env
        self.settings = settings
        self.nodes:   list[SensorNode] = []
        self.sink:    SensorNode | None = None
        self._build_topology()
        self._build_neighbors()

    # ------------------------------------------------------------------
    # Internal factory helpers
    # ------------------------------------------------------------------

    def _make_sink(self) -> SensorNode:
        sx, sy = self.settings.SINK_POSITION
        sink = SensorNode(
            node_id=0, x=sx, y=sy,
            env=self.env, settings=self.settings, is_sink=True,
        )
        self.sink = sink
        return sink

    def _make_node(self, node_id: int, x: float, y: float) -> SensorNode:
        return SensorNode(
            node_id=node_id, x=x, y=y,
            env=self.env, settings=self.settings, is_sink=False,
        )

    # ------------------------------------------------------------------
    # Topology dispatcher
    # ------------------------------------------------------------------

    def _build_topology(self) -> None:
        t = self.settings.TOPOLOGY
        if t not in self.VALID_TOPOLOGIES:
            raise ValueError(
                f"Invalid topology '{t}'. "
                f"Valid options: {sorted(self.VALID_TOPOLOGIES)}"
            )
        getattr(self, f"_build_{t.lower()}")()

    # ------------------------------------------------------------------
    # Random
    # ------------------------------------------------------------------

    def _build_random(self) -> None:
        cfg = self.settings
        self.nodes.append(self._make_sink())
        xs = np.random.uniform(0, cfg.AREA_WIDTH,  cfg.NUM_NODES - 1)
        ys = np.random.uniform(0, cfg.AREA_HEIGHT, cfg.NUM_NODES - 1)
        for i, (x, y) in enumerate(zip(xs, ys), start=1):
            self.nodes.append(self._make_node(i, float(x), float(y)))

    # ------------------------------------------------------------------
    # Grid  (ceil(sqrt(N)) × ceil(sqrt(N)), sink at SINK_POSITION)
    # ------------------------------------------------------------------

    def _build_grid(self) -> None:
        cfg = self.settings
        n    = cfg.NUM_NODES
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(math.sqrt(n))
        x_sp = cfg.AREA_WIDTH  / max(cols - 1, 1)
        y_sp = cfg.AREA_HEIGHT / max(rows - 1, 1)

        self.nodes.append(self._make_sink())
        nid = 1
        for row in range(rows):
            for col in range(cols):
                if nid >= n:
                    break
                self.nodes.append(
                    self._make_node(nid, col * x_sp, row * y_sp)
                )
                nid += 1
            if nid >= n:
                break

    # ------------------------------------------------------------------
    # Star  (sink at centre, others on circle)
    # ------------------------------------------------------------------

    def _build_star(self) -> None:
        cfg = self.settings
        cx, cy = cfg.SINK_POSITION
        radius  = min(cfg.AREA_WIDTH, cfg.AREA_HEIGHT) * 0.4
        self.nodes.append(self._make_sink())
        n = cfg.NUM_NODES
        for i in range(1, n):
            angle = 2 * math.pi * (i - 1) / max(n - 1, 1)
            x = max(0.0, min(cfg.AREA_WIDTH,  cx + radius * math.cos(angle)))
            y = max(0.0, min(cfg.AREA_HEIGHT, cy + radius * math.sin(angle)))
            self.nodes.append(self._make_node(i, x, y))

    # ------------------------------------------------------------------
    # Tree  (BFS from sink, branching_factor=3)
    # ------------------------------------------------------------------

    def _build_tree(self, branching_factor: int = 3) -> None:
        cfg = self.settings
        sink = self._make_sink()
        self.nodes.append(sink)
        n   = cfg.NUM_NODES
        nid = 1
        q: deque[tuple[SensorNode, int]] = deque([(sink, 0)])
        depth = 0
        while q and nid < n:
            level_size = len(q)
            depth += 1
            for _ in range(level_size):
                if nid >= n:
                    break
                parent, _ = q.popleft()
                for ci in range(branching_factor):
                    if nid >= n:
                        break
                    angle  = 2 * math.pi * ci / branching_factor
                    spread = min(cfg.AREA_WIDTH, cfg.AREA_HEIGHT) * 0.35 / depth
                    x = max(0.0, min(cfg.AREA_WIDTH,  parent.x + spread * math.cos(angle)))
                    y = max(0.0, min(cfg.AREA_HEIGHT, parent.y + spread * math.sin(angle)))
                    child = self._make_node(nid, x, y)
                    self.nodes.append(child)
                    q.append((child, depth))
                    nid += 1

    # ------------------------------------------------------------------
    # Neighbour discovery (RSSI-based, symmetric)
    # ------------------------------------------------------------------

    def _build_neighbors(self) -> None:
        for node in self.nodes:
            node.neighbors = [
                other for other in self.nodes
                if other.id != node.id and node.can_communicate(other)
            ]

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_node_by_id(self, node_id: int) -> SensorNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
