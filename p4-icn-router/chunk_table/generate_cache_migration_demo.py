#!/usr/bin/env python3
"""Animated GIF: multi-chunk delivery + gradual cache migration (chunk_table)."""
import math
import os

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import animation

plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP", "Noto Sans CJK", "IPAGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(__file__), "cache_migration_demo.gif")
N_CHUNKS = 4

# x positions along the backbone
X = {"consumer": 0.8, "s1": 2.8, "s2": 5.0, "s3": 7.2, "producer": 9.2}
Y = 5.0
CHUNK_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#e67e22"]
CHUNK_LABELS = ["chunk1", "chunk2", "chunk3", "chunk4"]


def draw_node(ax, x, y, label, sub="", kind="iwp"):
    if kind == "consumer":
        body = mpatches.FancyBboxPatch(
            (x - 0.35, y - 0.25), 0.7, 0.5,
            boxstyle="round,pad=0.02", linewidth=1.5,
            edgecolor="#2c3e50", facecolor="#ecf0f1",
        )
        ax.add_patch(body)
        ax.plot([x - 0.2, x + 0.2], [y - 0.45, y - 0.45], color="#2c3e50", lw=2)
    elif kind == "producer":
        for i, dx in enumerate([-0.15, 0.05, 0.25]):
            rect = mpatches.Rectangle(
                (x - 0.25 + dx, y - 0.35 + i * 0.05), 0.35, 0.55,
                linewidth=1.2, edgecolor="#2980b9", facecolor="#d6eaf8",
            )
            ax.add_patch(rect)
    else:
        cyl = mpatches.Circle((x, y), 0.32, facecolor="#5dade2", edgecolor="#1f618d", lw=2)
        ax.add_patch(cyl)
        for ang in [30, 150, 270]:
            rad = math.radians(ang)
            ax.annotate(
                "", xy=(x + 0.18 * math.cos(rad), y + 0.18 * math.sin(rad)),
                xytext=(x - 0.18 * math.cos(rad), y - 0.18 * math.sin(rad)),
                arrowprops=dict(arrowstyle="-|>", color="white", lw=1.2),
            )

    ax.text(x, y - 0.75, label, ha="center", va="top", fontsize=10, fontweight="bold")
    if sub:
        ax.text(x, y - 1.05, sub, ha="center", va="top", fontsize=8, color="#555")


def draw_backbone(ax):
    ax.plot([X["consumer"], X["producer"]], [Y, Y], color="#2c3e50", lw=2.5, zorder=1)
    for k in ("consumer", "s1", "s2", "s3", "producer"):
        kind = "consumer" if k == "consumer" else ("producer" if k == "producer" else "iwp")
        labels = {
            "consumer": ("Consumer", "情報要求者"),
            "s1": ("IWP1", "(s1)"),
            "s2": ("IWP2", "(s2)"),
            "s3": ("IWP3", "(s3)"),
            "producer": ("Producer", "情報提供者"),
        }
        draw_node(ax, X[k], Y, labels[k][0], labels[k][1], kind=kind)


def draw_producer_stacks(ax, visible_count=4):
    """Original chunks at producer (right side)."""
    px = X["producer"] + 0.55
    for i in range(visible_count):
        cy = Y + 0.9 - i * 0.42
        rect = mpatches.FancyBboxPatch(
            (px, cy - 0.14), 0.75, 0.28,
            boxstyle="round,pad=0.01", linewidth=1.5,
            edgecolor=CHUNK_COLORS[i], facecolor="white",
        )
        ax.add_patch(rect)
        ax.text(px + 0.375, cy, CHUNK_LABELS[i], ha="center", va="center", fontsize=7)


def draw_cache(ax, node_key, chunk_indices):
    """Draw cached chunks under a switch."""
    if not chunk_indices:
        return
    nx = X[node_key]
    base_y = Y - 1.55
    for j, ci in enumerate(sorted(chunk_indices)):
        cx = nx - 0.45 + j * 0.28
        rect = mpatches.Rectangle(
            (cx, base_y), 0.24, 0.22,
            linewidth=1.2, edgecolor=CHUNK_COLORS[ci], facecolor=CHUNK_COLORS[ci], alpha=0.35,
        )
        ax.add_patch(rect)
        ax.text(cx + 0.12, base_y + 0.11, str(ci + 1), ha="center", va="center",
                fontsize=6, fontweight="bold", color=CHUNK_COLORS[ci])
    ax.text(nx, base_y - 0.25, f"CS ({len(chunk_indices)}/4)",
            ha="center", fontsize=7, color="#555")


def draw_moving_packet(ax, x, label, color, ptype="data"):
    w, h = 0.85, 0.32
    rect = mpatches.FancyBboxPatch(
        (x - w / 2, Y + 0.55), w, h,
        boxstyle="round,pad=0.02", linewidth=1.8,
        edgecolor=color, facecolor=color, alpha=0.25 if ptype == "data" else 0.15,
    )
    ax.add_patch(rect)
    txt = label if ptype == "data" else "Interest"
    ax.text(x, Y + 0.55 + h / 2, txt, ha="center", va="center",
            fontsize=7, fontweight="bold", color=color)


def lerp(a, b, t):
    return a + (b - a) * t


def segment_x(name_a, name_b, t):
    return lerp(X[name_a], X[name_b], t)


def copy_cache(cache):
    return {k: set(v) for k, v in cache.items()}


def build_timeline():
    """Return list of frame dicts."""
    frames = []

    def hold(state, n=4):
        for _ in range(n):
            frames.append(dict(state))

    def move_data(state, chunk_i, src, dst, steps=8, cache_on_pass=None, **extra):
        """Move Data packet; cache at node when packet passes it (flag=1 受信時)."""
        cache = copy_cache(state.get("cache", {"s1": set(), "s2": set(), "s3": set()}))
        for s in range(steps + 1):
            t = s / steps
            x = segment_x(src, dst, t)
            frame_cache = copy_cache(cache)
            # 左方向へ進む Data がスイッチを通過した時点で CS に保存
            if cache_on_pass is not None and x <= X[cache_on_pass]:
                frame_cache[cache_on_pass].add(chunk_i)
            st = dict(state, **extra)
            st["cache"] = frame_cache
            st["packet"] = {
                "x": x,
                "label": CHUNK_LABELS[chunk_i],
                "color": CHUNK_COLORS[chunk_i],
                "ptype": "data",
            }
            frames.append(st)
        if cache_on_pass is not None:
            cache[cache_on_pass].add(chunk_i)
        out = dict(state, **extra)
        out["cache"] = cache
        out["packet"] = None
        return out

    def move_interest(state, path, steps=10, **extra):
        segs = list(zip(path[:-1], path[1:]))
        per = max(steps // len(segs), 2)
        for a, b in segs:
            for s in range(per + 1):
                t = s / per
                st = dict(state, **extra)
                st["packet"] = {
                    "x": segment_x(a, b, t),
                    "label": "Interest",
                    "color": "#f39c12",
                    "ptype": "interest",
                }
                frames.append(st)

    # --- Phase 1: first fetch ---
    p1 = {
        "phase_title": "Phase 1: 初回取得（Producer 応答）",
        "phase_desc": "Interest 転送 → Producer が chunk1〜4 を別パケットで送信",
        "cache": {"s1": set(), "s2": set(), "s3": set()},
        "producer_visible": 4,
    }
    hold(p1, 3)
    move_interest(p1, ["consumer", "s1", "s2", "s3", "producer"], steps=12,
                  phase_desc="Interest が Producer まで到達（clone なし）")
    p1_state = dict(p1, phase_desc="Producer が 4 本の Data を個別送信", producer_visible=4)
    hold(p1_state, 2)
    for ci in range(N_CHUNKS):
        p1_state = move_data(
            dict(p1_state, phase_desc=f"{CHUNK_LABELS[ci]} 通過 → s3 が CS に保存（flag=1）"),
            ci, "producer", "consumer", steps=10, cache_on_pass="s3",
        )
    p1_end = dict(p1_state,
                  phase_desc="各 Data 通過時に s3 が保存（下流 s1/s2 は flag=0 で非保存）",
                  producer_visible=4)
    hold(p1_end, 6)

    # --- Phase 2: s3 hit -> cache to s2 ---
    p2 = dict(p1_end,
              phase_title="Phase 2: 2回目 Interest（s3 ヒット）",
              phase_desc="s3 から Data 生成 → s2 が受信ごとに CS 保存",
              cache={"s1": set(), "s2": set(), "s3": {0, 1, 2, 3}})
    hold(p2, 2)
    move_interest(dict(p2, phase_desc="Interest → s3 でキャッシュヒット"),
                  ["consumer", "s1", "s2", "s3"], steps=8)
    p2_state = dict(p2, phase_desc="s3 から 4 本の Data を順次配信")
    for ci in range(N_CHUNKS):
        p2_state = move_data(
            dict(p2_state, phase_desc=f"{CHUNK_LABELS[ci]} 通過 → s2 が CS に保存"),
            ci, "s3", "consumer", steps=8, cache_on_pass="s2",
        )
    p2_end = dict(p2_state,
                  phase_desc="全 chunk 配信後: s3 CS クリア",
                  cache={"s1": set(), "s2": {0, 1, 2, 3}, "s3": set()})
    hold(p2_end, 6)

    # --- Phase 3: s2 hit -> cache to s1 ---
    p3 = dict(p2_end,
              phase_title="Phase 3: 3回目 Interest（s2 ヒット）",
              phase_desc="s2 から Data 生成 → s1 が受信ごとに CS 保存",
              cache={"s1": set(), "s2": {0, 1, 2, 3}, "s3": set()})
    hold(p3, 2)
    move_interest(dict(p3, phase_desc="Interest → s2 でキャッシュヒット"),
                  ["consumer", "s1", "s2"], steps=8)
    p3_state = dict(p3, phase_desc="s2 から 4 本の Data を順次配信")
    for ci in range(N_CHUNKS):
        p3_state = move_data(
            dict(p3_state, phase_desc=f"{CHUNK_LABELS[ci]} 通過 → s1 が CS に保存"),
            ci, "s2", "consumer", steps=8, cache_on_pass="s1",
        )
    p3_end = dict(p3_state,
                  phase_desc="全 chunk 配信後: s2 CS クリア",
                  cache={"s1": {0, 1, 2, 3}, "s2": set(), "s3": set()})
    hold(p3_end, 6)

    # --- Phase 4: cache hit at s1 ---
    p4 = dict(p3_end,
              phase_title="Phase 4: 4回目 Interest（s1 ヒット）",
              phase_desc="Producer 不要 — s1 から 4 chunk 配信",
              cache={"s1": {0, 1, 2, 3}, "s2": set(), "s3": set()})
    hold(p4, 2)
    move_interest(dict(p4, phase_desc="Interest → s1 で停止（Producer 未到達）"),
                  ["consumer", "s1"], steps=6)
    p4_state = dict(p4, phase_desc="s1 から 4 本の Data を順次配信（CS 保持）")
    for ci in range(N_CHUNKS):
        p4_state = move_data(
            dict(p4_state, phase_desc=f"{CHUNK_LABELS[ci]} → Consumer へ"),
            ci, "s1", "consumer", steps=7,
        )
    p4_end = dict(p4_state,
                  phase_desc="完了: s1 に CS 保持（Consumer 直近）",
                  producer_visible=4)
    hold(p4_end, 8)

    return frames


def draw_frame(ax, state):
    ax.clear()
    ax.set_xlim(-0.2, 10.8)
    ax.set_ylim(2.0, 7.8)
    ax.axis("off")

    ax.text(5.0, 7.5, "複数 Data 送信 + 段階的キャッシュ移動",
            ha="center", fontsize=13, fontweight="bold")
    ax.text(5.0, 7.05, state.get("phase_title", ""), ha="center",
            fontsize=11, color="#1a5276", fontweight="bold")
    ax.text(5.0, 6.65, state.get("phase_desc", ""), ha="center", fontsize=9, color="#555")

    draw_backbone(ax)
    draw_producer_stacks(ax, state.get("producer_visible", 4))

    cache = state.get("cache", {"s1": set(), "s2": set(), "s3": set()})
    for node in ("s1", "s2", "s3"):
        draw_cache(ax, node, cache.get(node, set()))

    pkt = state.get("packet")
    if pkt:
        draw_moving_packet(ax, pkt["x"], pkt["label"], pkt["color"],
                           pkt.get("ptype", "data"))

    # Legend
    leg_y = 2.25
    ax.add_patch(mpatches.Rectangle((0.5, leg_y), 0.35, 0.18,
                                    facecolor="#f39c12", edgecolor="#d68910", alpha=0.4))
    ax.text(0.95, leg_y + 0.09, "Interest", va="center", fontsize=7)
    for i, c in enumerate(CHUNK_COLORS):
        ax.add_patch(mpatches.Rectangle((2.0 + i * 1.5, leg_y), 0.35, 0.18,
                                        facecolor=c, edgecolor=c, alpha=0.4))
        ax.text(2.45 + i * 1.5, leg_y + 0.09, CHUNK_LABELS[i], va="center", fontsize=7)
    ax.text(8.5, leg_y + 0.09, "CS = Content Store (Register)", va="center", fontsize=7, color="#666")


def main():
    frames = build_timeline()
    fig, ax = plt.subplots(figsize=(11, 5.5))

    def update(i):
        draw_frame(ax, frames[i])
        return []

    anim = animation.FuncAnimation(
        fig, update, frames=len(frames), interval=280, blit=False, repeat=True,
    )
    anim.save(OUT, writer="pillow", dpi=110)
    plt.close(fig)
    print(f"Wrote {OUT} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
