"""
main.py — WSN Simulator: Gradient Routing vs Pure Flooding
"""
from __future__ import annotations

import math
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import simpy

import config.settings as settings
from models.channel import RicianChannelModel
from models.network import Network
from models.packet import Packet
from protocols.gradient import GradientRouting
from protocols.flooding import FloodingRouting
from protocols.ADUP import ADUPRouting
from utils.metrics import MetricsCollector


# =============================================================================
# IEEE publication-quality style
# =============================================================================
plt.rcParams.update({
    "font.family":     "serif",
    "font.serif":      ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size":       9,
    "axes.labelsize":  9,
    "axes.titlesize":  10,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "text.usetex":     False,
})

IEEE_DOUBLE = 7.16


# =============================================================================
# Seed helper — call before every Network/simulation construction
# =============================================================================

def _reset_seed(cfg) -> None:
    if getattr(cfg, "RANDOM_SEED", None) is not None:
        np.random.seed(cfg.RANDOM_SEED)
        random.seed(cfg.RANDOM_SEED)


# =============================================================================
# Topology plot  (called once, after the first network is built)
# =============================================================================

def _plot_topology(network, cfg, output_path: str = "topology.png") -> None:
    nodes = network.nodes
    finite_nodes = [n for n in nodes if math.isfinite(n.gradient_level)]
    inf_nodes    = [n for n in nodes if not math.isfinite(n.gradient_level)]

    fig, ax = plt.subplots(figsize=(IEEE_DOUBLE, IEEE_DOUBLE * 0.75), dpi=300)

    drawn: set[frozenset] = set()
    for node in nodes:
        for nb in node.neighbors:
            edge = frozenset([node.id, nb.id])
            if edge not in drawn:
                ax.plot([node.x, nb.x], [node.y, nb.y], color="gray",
                        linewidth=0.4, zorder=1, alpha=0.35)
                drawn.add(edge)

    regular = [n for n in finite_nodes if not n.is_sink]
    if regular:
        sc = ax.scatter([n.x for n in regular], [n.y for n in regular],
                        c=[n.gradient_level for n in regular], cmap="plasma_r",
                        s=45, zorder=3, edgecolors="#333333", linewidths=0.4)
        cbar = fig.colorbar(sc, ax=ax, shrink=0.75, pad=0.02)
        cbar.set_label("Gradient Level (hops to Sink)", fontsize=8)
        cbar.ax.tick_params(labelsize=7)

    if inf_nodes:
        ax.scatter([n.x for n in inf_nodes], [n.y for n in inf_nodes],
                   c="#e63946", s=40, marker="x", linewidths=1.2, zorder=4,
                   label=f"Unreachable ({len(inf_nodes)})")

    if len(nodes) <= 60:
        for n in nodes:
            if not n.is_sink:
                ax.annotate(str(n.id), xy=(n.x, n.y), fontsize=5,
                            color="white", ha="center", va="center",
                            fontweight="bold", zorder=5)

    ax.scatter([network.sink.x], [network.sink.y], c="#e63946", s=120,
               marker="s", zorder=6, edgecolors="black", linewidths=0.8,
               label="Sink (node 0)")
    ax.annotate(f"Sink\n({network.sink.x:.0f},{network.sink.y:.0f})",
                xy=(network.sink.x, network.sink.y), xytext=(6, 6),
                textcoords="offset points", fontsize=7, fontweight="bold",
                color="#c0392b", zorder=7)

    total_links = sum(len(n.neighbors) for n in nodes) // 2
    avg_nb = sum(len(n.neighbors) for n in nodes) / max(1, len(nodes))
    ax.text(0.01, 0.01,
            f"Nodes: {len(nodes)}  |  Links: {total_links}\n"
            f"Avg neighbours: {avg_nb:.1f}\n"
            f"Reachable: {len(finite_nodes)}/{len(nodes)}",
            transform=ax.transAxes, fontsize=7, verticalalignment="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8,
                      edgecolor="black", linewidth=0.5))

    all_x = [n.x for n in nodes]
    all_y = [n.y for n in nodes]
    px, py = cfg.AREA_WIDTH * 0.05, cfg.AREA_HEIGHT * 0.05
    ax.set_xlim(min(all_x) - px, max(all_x) + px)
    ax.set_ylim(min(all_y) - py, max(all_y) + py)
    ax.set_xlabel("X Position (m)")
    ax.set_ylabel("Y Position (m)")
    ax.set_title(f"WSN Topology — {cfg.TOPOLOGY} | {cfg.NUM_NODES} nodes | "
                 f"seed={cfg.RANDOM_SEED}", fontweight="bold", pad=6)
    legend = ax.legend(loc="upper right", frameon=True, fancybox=False,
                       framealpha=0.9, edgecolor="black")
    legend.get_frame().set_linewidth(0.5)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", linewidth=0.3, alpha=0.4)
    fig.tight_layout(pad=0.4)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[VIZ] Topology saved: {output_path}")


# =============================================================================
# Progress monitor
# =============================================================================

def _progress_monitor(env: simpy.Environment, total_time: float,
                       interval_s: float = 30.0):
    while env.now < total_time:
        yield env.timeout(interval_s)
        pct = env.now / total_time * 100.0
        print(f"  [SIM] {pct:5.1f}%  t={env.now:.1f}/{total_time:.1f} s",
              flush=True)


# =============================================================================
# Per-algorithm result summary
# =============================================================================

def _print_summary_labeled(cfg, network, metrics: MetricsCollector,
                            label: str) -> None:
    raw = metrics.get_raw_data()
    n_created   = len(raw["created"])
    n_delivered = len(raw["delivered"])
    n_dropped   = metrics.get_total_drops()
    n_non_sink  = sum(1 for n in network.nodes if not n.is_sink)

    is_flooding_downlink = "flooding" in label.lower() and "[downlink]" in label.lower()

    if is_flooding_downlink:
        pdr      = metrics.get_pdr_broadcast(n_non_sink)
        bc_count = raw["bc_deliveries_count"]
        pdr_str  = (f"  PDR (broadcast)   : {pdr:.2f} %"
                    f"  ({bc_count} node-deliveries / "
                    f"{n_created} pkts × {n_non_sink} nodes)")
    else:
        pdr     = metrics.get_pdr()
        pdr_str = f"  PDR               : {pdr:.2f} %"

    sep  = "=" * 60
    dash = "-" * 60
    print()
    print(sep)
    print(f"   {label.upper()} — RESULTS")
    print(sep)
    print(f"  Packets created   : {n_created}")
    print(f"  Packets delivered : {n_delivered}")
    print(f"  Packets dropped   : {n_dropped}")
    print(dash)
    print(pdr_str)
    print(f"  NTL (total TX)    : {metrics.get_ntl():,}")
    print(sep)


# =============================================================================
# Comparison table
# =============================================================================

def _print_comparison_table(results: dict[str, dict]) -> None:
    labels = list(results.keys())
    metrics_info = [
        ("PDR (%)",  "pdr", "{:.2f}"),
        ("NTL (TX)", "ntl", "{:,}"),
    ]

    col_w = 20
    sep  = "=" * (18 + col_w * len(labels))
    dash = "-" * (18 + col_w * len(labels))

    print()
    print(sep)
    print("   ALGORITHM COMPARISON")
    print(sep)
    print(f"  {'Metric':<16}" + "".join(f"{lb:>{col_w}}" for lb in labels))
    print(dash)
    for name, key, fmt in metrics_info:
        row = f"  {name:<16}"
        for lb in labels:
            row += f"{fmt.format(results[lb][key]):>{col_w}}"
        print(row)
    print(sep)
    print()


# =============================================================================
# Comparison chart
# =============================================================================

def _plot_comparison(results: dict[str, dict],
                     output_path: str = "comparison.png") -> None:
    labels        = list(results.keys())
    metrics_keys  = ["pdr",     "ntl",        "ntl_bytes"]
    metric_labels = ["PDR (%)", "NTL (pkts)", "NTL (bytes)"]
    bar_colors    = ["#2E86AB", "#E63946", "#2CA02C"]

    fig, axes = plt.subplots(1, len(metrics_keys),
                             figsize=(IEEE_DOUBLE, 2.8), dpi=300)
    fig.suptitle("Algorithm Comparison", fontweight="bold", y=1.02)

    for ax, key, mlabel in zip(axes, metrics_keys, metric_labels):
        vals = [results[lb][key] for lb in labels]
        bars = ax.bar(labels, vals,
                      color=[bar_colors[i % len(bar_colors)]
                             for i in range(len(labels))],
                      edgecolor="black", linewidth=0.5, alpha=0.85, width=0.5)
        for bar, v in zip(bars, vals):
            if key == "ntl_bytes":
                fmt = f"{v/1000:.1f}k" if v >= 1000 else str(int(v))
            elif key == "ntl":
                fmt = f"{v:,.0f}"
            else:
                fmt = f"{v:.2f}"
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.02 if v > 0 else 0.01,
                    fmt, ha="center", va="bottom", fontsize=6)
        ax.set_title(mlabel, fontweight="bold", fontsize=8)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels([lb.replace(" ", "\n") for lb in labels], fontsize=6)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(axis="y", labelsize=6)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(
                lambda x, _: f"{x:,.0f}" if x >= 1000 else f"{x:.2f}"
            )
        )

    fig.tight_layout(pad=0.4)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[VIZ] Comparison chart saved: {output_path}")


# =============================================================================
# Comparison table — both directions
# =============================================================================

def _print_comparison_table_both(results: dict[str, dict]) -> None:
    """Print table with uplink and downlink columns for each algorithm."""
    labels = list(results.keys())
    metrics_info = [
        ("PDR (%)",  "pdr", "{:.2f}"),
        ("NTL (TX)", "ntl", "{:,}"),
    ]
    directions = ["uplink", "downlink"]
    col_headers = [f"{lb}\n({d})" for lb in labels for d in directions]
    col_w = 18
    sep  = "=" * (18 + col_w * len(col_headers))
    dash = "-" * (18 + col_w * len(col_headers))

    print()
    print(sep)
    print("   ALGORITHM COMPARISON (UPLINK vs DOWNLINK)")
    print(sep)
    print(f"  {'Metric':<16}" + "".join(f"{h:>{col_w}}" for h in col_headers))
    print(dash)
    for name, key, fmt in metrics_info:
        row = f"  {name:<16}"
        for lb in labels:
            for d in directions:
                row += f"{fmt.format(results[lb][d][key]):>{col_w}}"
        print(row)
    print(sep)
    print()


# =============================================================================
# Comparison chart — both directions (grouped bars)
# =============================================================================

def _plot_comparison_both(results: dict[str, dict],
                           output_path: str = "comparison.png") -> None:
    labels        = list(results.keys())
    metrics_keys  = ["pdr",     "ntl",       "ntl_bytes"]
    metric_labels = ["PDR (%)", "NTL (pkts)", "NTL (bytes)"]
    directions    = ["uplink", "downlink"]

    color_map = {
        "uplink":   ["#2E86AB", "#E63946", "#2CA02C"],
        "downlink": ["#7EC8E3", "#F4A0A8", "#98DF8A"],
    }
    hatch_map = {"uplink": "", "downlink": "//"}

    n_groups = len(labels)
    n_dirs   = len(directions)
    bar_w    = 0.35
    x        = np.arange(n_groups)

    # 3 subplots hàng ngang + legend row bên dưới
    fig, axes = plt.subplots(1, len(metrics_keys),
                             figsize=(IEEE_DOUBLE, 2.8), dpi=300)
    fig.suptitle("Algorithm Comparison — Uplink vs Downlink",
                 fontweight="bold", y=1.02)

    for ax, key, mlabel in zip(axes, metrics_keys, metric_labels):
        for d_idx, direction in enumerate(directions):
            vals = [results[lb][direction][key] for lb in labels]
            offset = (d_idx - (n_dirs - 1) / 2) * bar_w
            bars = ax.bar(
                x + offset, vals,
                width=bar_w,
                color=[color_map[direction][i % len(color_map[direction])]
                       for i in range(n_groups)],
                edgecolor="black", linewidth=0.4,
                alpha=0.9, hatch=hatch_map[direction],
            )
            for bar, v in zip(bars, vals):
                if key == "ntl_bytes":
                    fmt = f"{v/1000:.1f}k" if v >= 1000 else str(int(v))
                elif key == "ntl":
                    fmt = f"{v:,.0f}"
                else:
                    fmt = f"{v:.2f}"
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() * 1.02 if v > 0 else 0.01,
                        fmt, ha="center", va="bottom", fontsize=5)

        ax.set_title(mlabel, fontweight="bold", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([lb.replace(" ", "\n") for lb in labels], fontsize=6)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(axis="y", labelsize=6)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(
                lambda v, _: f"{v:,.0f}" if v >= 1000 else f"{v:.2f}"
            )
        )

    # Legend chung đặt bên dưới tất cả subplots, không đè lên đồ thị
    handles = [
        plt.Rectangle((0, 0), 1, 1,
                       facecolor="#888888",
                       hatch=hatch_map[d],
                       edgecolor="black", linewidth=0.4,
                       label=d.capitalize())
        for d in directions
    ]
    fig.legend(handles=handles,
               loc="lower center",
               ncol=len(directions),
               fontsize=7,
               frameon=True,
               fancybox=False,
               edgecolor="black",
               bbox_to_anchor=(0.5, -0.08))

    fig.tight_layout(pad=0.4)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[VIZ] Comparison chart saved: {output_path}")


# =============================================================================
# Main runner
# =============================================================================

def compare_algorithms(cfg=settings) -> None:
    """
    Run uplink / downlink / both based on cfg.SIM_MODE.
    - "uplink"   : nodes → sink, single bar chart
    - "downlink" : sink → nodes, single bar chart
    - "both"     : run uplink then downlink, grouped bar chart
    """
    sim_mode = getattr(cfg, "SIM_MODE", "uplink").lower()

    algorithms = [
        ("Gradient Routing", GradientRouting),
        ("ADUP",             ADUPRouting),
        ("Flooding",         FloodingRouting),
    ]

    # results[label]["uplink"|"downlink"] = metrics dict
    results: dict[str, dict] = {}
    topology_saved = False

    directions = []
    if sim_mode == "both":
        directions = ["uplink", "downlink"]
    else:
        directions = [sim_mode]

    for direction in directions:
        print(f"\n{'#'*60}")
        print(f"  DIRECTION: {direction.upper()}")
        print(f"{'#'*60}")

        for label, ProtocolClass in algorithms:
            print(f"\n{'='*60}")
            print(f"  Running: {label} [{direction}]")
            print(f"{'='*60}")

            _reset_seed(cfg)

            env     = simpy.Environment()
            network = Network(env, cfg)
            channel = RicianChannelModel(
                cfg.LUT_PATH,
                collision_penalty=getattr(cfg, "COLLISION_PENALTY_PER_TX", 0.85),
            )
            metrics = MetricsCollector()
            routing = ProtocolClass(network, channel, metrics, cfg)

            routing.run_setup_phase()

            if not topology_saved:
                _plot_topology(network, cfg, output_path="topology.png")
                topology_saved = True

            if direction == "uplink":
                routing.start_forwarding()
            else:
                routing.start_downlink_forwarding()

            env.process(_progress_monitor(env, cfg.SIM_DURATION,
                                          getattr(cfg, "PROGRESS_INTERVAL_S", 30.0)))
            env.run(until=cfg.SIM_DURATION)

            for node in network.nodes:
                metrics.record_energy(node.energy_consumed)

            _print_summary_labeled(cfg, network, metrics,
                                   f"{label} [{direction}]")

            is_flooding_dl = (label == "Flooding" and direction == "downlink")
            n_non_sink     = sum(1 for n in network.nodes if not n.is_sink)
            pdr_val = (metrics.get_pdr_broadcast(n_non_sink)
                       if is_flooding_dl else metrics.get_pdr())
            total_bytes = sum(n.bytes_transmitted for n in network.nodes)

            if label not in results:
                results[label] = {}
            results[label][direction] = {
                "pdr":        pdr_val,
                "ntl":        metrics.get_ntl(),
                "ntl_bytes":  total_bytes,
                "avg_rtt":    metrics.get_avg_rtt(),
                "avg_hops":   metrics.get_avg_hop_count(),
                "energy_mj":  metrics.get_total_energy(),
            }

    if sim_mode == "both":
        _print_comparison_table_both(results)
        _plot_comparison_both(results, output_path="comparison.png")
    else:
        # Flatten for single-direction output
        flat = {label: results[label][sim_mode] for label in results}
        _print_comparison_table(flat)
        _plot_comparison(flat, output_path="comparison.png")


if __name__ == "__main__":
    compare_algorithms()
