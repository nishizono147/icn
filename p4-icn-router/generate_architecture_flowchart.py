#!/usr/bin/env python3
"""Generate PNG flowcharts from 設計メモ.txt architecture."""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import os

OUT_DIR = os.path.dirname(__file__)


def _box(ax, x, y, w, h, text, fc="#ffffff", ec="#333333", fontsize=9):
    patch = FancyBboxPatch(
        (x - w / 2, y - h / 2),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.5,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, wrap=True)


def _diamond(ax, x, y, w, h, text, fc="#ffffff", ec="#333333", fontsize=8):
    pts = [
        (x, y + h / 2),
        (x + w / 2, y),
        (x, y - h / 2),
        (x - w / 2, y),
    ]
    from matplotlib.patches import Polygon

    poly = Polygon(pts, closed=True, linewidth=1.5, edgecolor=ec, facecolor=fc)
    ax.add_patch(poly)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize)


def _arrow(ax, x1, y1, x2, y2, label=None):
    arr = FancyArrowPatch(
        (x1, y1),
        (x2, y2),
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.2,
        color="#444444",
        connectionstyle="arc3,rad=0",
    )
    ax.add_patch(arr)
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        ax.text(mx + 0.15, my, label, fontsize=7, color="#555555")


def draw_interest_flow():
    fig, ax = plt.subplots(figsize=(10, 14))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 14)
    ax.axis("off")
    ax.set_title(
        "Interest Processing Flow (IWP)",
        fontsize=13,
        fontweight="bold",
        pad=16,
    )

    y = 13.0
    _box(ax, 5, y, 3.2, 0.7, "Receive Interest", fc="#ecf0f1")
    _arrow(ax, 5, y - 0.35, 5, y - 0.95)
    y -= 1.3
    _box(ax, 5, y, 4.0, 0.7, "Record ingress port in PIT", fc="#d6eaf8", ec="#2980b9")
    _arrow(ax, 5, y - 0.35, 5, y - 0.95)
    y -= 1.3
    _diamond(ax, 5, y, 3.6, 1.2, "LCST lookup\n(on-path)", fc="#d5f5e3", ec="#27ae60")
    _arrow(ax, 5, y - 0.6, 5, y - 1.2, "miss")
    y -= 1.8
    _diamond(ax, 5, y, 3.6, 1.2, "ECST lookup\n(off-path)", fc="#d6eaf8", ec="#2980b9")
    _arrow(ax, 5, y - 0.6, 5, y - 1.2, "miss")
    y -= 1.8
    _diamond(ax, 5, y, 3.6, 1.2, "FIB lookup\n(LPM)", fc="#fdebd0", ec="#e67e22")
    _arrow(ax, 5 + 1.8, y, 8.2, y, "miss")
    _box(ax, 8.2, y, 2.0, 0.6, "Drop", fc="#fadbd8", ec="#c0392b", fontsize=8)
    _arrow(ax, 5, y - 0.6, 5, y - 1.2, "hit")
    y -= 1.8

    _box(ax, 5, y, 4.2, 0.8, "Get next-hop iwpid", fc="#fdebd0", ec="#e67e22")
    _arrow(ax, 5, y - 0.4, 5, y - 1.0)
    y -= 1.5
    _box(ax, 5, y, 4.5, 0.9, "Interest forward\n(NMT -> NRS+IP)", fc="#e8daef", ec="#8e44ad")

    # LCST hit -> Data
    _arrow(ax, 5 - 1.8, 10.0, 1.8, 10.0, "hit")
    _box(ax, 1.8, 10.0, 2.4, 0.8, "Data send path", fc="#e8daef", ec="#8e44ad", fontsize=8)
    _arrow(ax, 1.8, 9.6, 1.8, 8.5)
    _box(ax, 1.8, 8.1, 2.8, 0.9, "PIT reverse\nor IP forward", fc="#e8daef", ec="#8e44ad", fontsize=8)

    # ECST hit -> Interest forward
    _arrow(ax, 5 + 1.8, 8.2, 8.2, 8.2, "hit")
    _box(ax, 8.2, 8.2, 2.6, 0.8, "Get cache-holder\niwpid", fc="#d6eaf8", ec="#2980b9", fontsize=8)
    _arrow(ax, 8.2, 7.8, 6.5, 6.3)

    plt.tight_layout()
    path = os.path.join(OUT_DIR, "architecture_interest_flow.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def draw_interest_forward():
    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8)
    ax.axis("off")
    ax.set_title(
        "Interest Forwarding (NMT / NRS)",
        fontsize=13,
        fontweight="bold",
        pad=16,
    )

    _box(ax, 5, 7.2, 4.5, 0.7, "Target iwpid known", fc="#ecf0f1")
    _arrow(ax, 5, 6.85, 5, 6.35)
    _diamond(ax, 5, 5.9, 3.8, 1.2, "NMT lookup\n(adjacent IWP?)", fc="#d6eaf8", ec="#2980b9")

    _arrow(ax, 5 - 1.9, 5.9, 2.0, 5.9, "hit")
    _box(ax, 2.0, 5.9, 2.6, 0.9, "IP encapsulate\nkeep consumer IP", fc="#e8f4fc", ec="#2980b9", fontsize=8)
    _arrow(ax, 2.0, 5.45, 2.0, 4.85)
    _box(ax, 2.0, 4.5, 2.8, 0.8, "Direct port output\n(no IP table)", fc="#e8f4fc", ec="#2980b9", fontsize=8)
    _arrow(ax, 2.0, 4.1, 2.0, 3.5)
    _box(ax, 2.0, 3.15, 2.2, 0.6, "Next IWP", fc="#d5f5e3", ec="#27ae60", fontsize=8)

    _arrow(ax, 5, 5.3, 5, 4.7, "miss")
    _diamond(ax, 5, 4.35, 3.4, 1.1, "NRS query\n(iwpid->IP)", fc="#eafaf1", ec="#27ae60")
    _arrow(ax, 5, 3.8, 5, 3.2, "hit")
    _box(ax, 5, 2.85, 3.2, 0.8, "IP encapsulate\ndst = target IWP", fc="#fdebd0", ec="#e67e22", fontsize=8)
    _arrow(ax, 5, 2.45, 5, 1.85)
    _box(ax, 5, 1.5, 3.5, 0.8, "Normal IP forward\n(via IP routers)", fc="#fdebd0", ec="#e67e22", fontsize=8)
    _arrow(ax, 5, 1.1, 5, 0.55)
    _box(ax, 5, 0.25, 2.2, 0.5, "Next IWP", fc="#d5f5e3", ec="#27ae60", fontsize=8)

    plt.tight_layout()
    path = os.path.join(OUT_DIR, "architecture_interest_forward.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def draw_data_flow():
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ax.set_title("Data Forwarding Flow (IWP)", fontsize=13, fontweight="bold", pad=16)

    _box(ax, 5, 9.2, 4.0, 0.7, "Send / receive Data", fc="#ecf0f1")
    _arrow(ax, 5, 8.85, 5, 8.35)
    _box(ax, 5, 8.0, 4.5, 0.8, "IP encapsulate\n(dst = consumer IP)", fc="#d5f5e3", ec="#27ae60")
    _arrow(ax, 5, 7.6, 5, 7.1)
    _diamond(ax, 5, 6.65, 3.4, 1.1, "PIT lookup", fc="#d6eaf8", ec="#2980b9")
    _arrow(ax, 5, 6.1, 5, 5.55, "hit")
    _box(ax, 5, 5.2, 3.5, 0.7, "Forward to PIT port", fc="#d6eaf8", ec="#2980b9")
    _arrow(ax, 5 - 1.7, 6.65, 2.0, 6.65, "miss")
    _box(ax, 2.0, 6.65, 2.8, 0.7, "Normal IP forward", fc="#fdebd0", ec="#e67e22", fontsize=8)
    _arrow(ax, 2.0, 6.3, 2.0, 5.55)
    _arrow(ax, 5, 4.85, 5, 4.35)
    _diamond(ax, 5, 3.95, 3.2, 1.0, "Next hop\nIWP or IP?", fc="#ecf0f1")
    _arrow(ax, 5 - 1.6, 3.95, 2.2, 3.95, "IP router")
    _box(ax, 2.2, 3.95, 2.4, 0.7, "IP-only forward", fc="#fdebd0", ec="#e67e22", fontsize=8)
    _arrow(ax, 5, 3.45, 5, 2.9, "IWP")
    _box(ax, 5, 2.55, 3.0, 0.7, "IWP ICN process", fc="#e8f4fc", ec="#2980b9")
    _arrow(ax, 3.5, 3.5, 5, 1.5)
    _arrow(ax, 5, 2.2, 5, 1.65)
    _box(ax, 5, 1.3, 2.8, 0.7, "Reach Consumer", fc="#d5f5e3", ec="#27ae60")

    ax.text(
        5,
        0.4,
        "Transition: consumer IP in Data -> no PIT multicast",
        ha="center",
        fontsize=8,
        color="#777777",
        style="italic",
    )

    plt.tight_layout()
    path = os.path.join(OUT_DIR, "architecture_data_flow.png")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    paths = [
        draw_interest_flow(),
        draw_interest_forward(),
        draw_data_flow(),
    ]
    for p in paths:
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
