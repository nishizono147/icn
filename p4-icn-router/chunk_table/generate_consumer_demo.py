#!/usr/bin/env python3
"""Generate an animated GIF demo of Consumer chunk reassembly (receive.py)."""
import os

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import animation

plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP", "Noto Sans CJK", "IPAGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(__file__), "consumer_reassemble_demo.gif")
CONTENT_ID = 4
TOTAL = 4
CHUNK_SIZE = 256
MD5 = "305313081da5f5b097e867a1f68f11c3"

COLORS = ["#3498db", "#2ecc71", "#e67e22", "#9b59b6"]
HOLD = 6  # frames to hold each step


def draw_frame(ax, step, received):
    ax.clear()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ax.set_title(
        "Consumer (h1): chunk 再構成デモ",
        fontsize=14,
        fontweight="bold",
        pad=12,
    )

    # Producer / network hint
    ax.text(1.0, 9.2, "s1 → h1  Data パケット受信 (receive.py / Scapy sniff)",
            fontsize=9, color="#555")

    # Slot boxes
    slot_w, slot_h = 1.6, 1.2
    start_x = 1.2
    y_slots = 6.8
    for i in range(TOTAL):
        x = start_x + i * 2.0
        filled = i in received
        face = COLORS[i] if filled else "#ecf0f1"
        edge = COLORS[i] if filled else "#bdc3c7"
        rect = mpatches.FancyBboxPatch(
            (x, y_slots), slot_w, slot_h,
            boxstyle="round,pad=0.02,rounding_size=0.08",
            linewidth=2, edgecolor=edge, facecolor=face, alpha=0.9,
        )
        ax.add_patch(rect)
        ax.text(x + slot_w / 2, y_slots + slot_h / 2 + 0.15,
                f"chunk {i}", ha="center", va="center", fontsize=10, fontweight="bold")
        if filled:
            ax.text(x + slot_w / 2, y_slots + slot_h / 2 - 0.25,
                    "256 B", ha="center", va="center", fontsize=8, color="#2c3e50")
        else:
            ax.text(x + slot_w / 2, y_slots + slot_h / 2 - 0.25,
                    "待機", ha="center", va="center", fontsize=8, color="#95a5a6")

    ax.text(5.0, 8.5, f"buffers[{CONTENT_ID}]  —  {len(received)}/{TOTAL} chunks",
            ha="center", fontsize=11, color="#2c3e50")

    # Progress bar
    bar_x, bar_y, bar_w, bar_h = 1.2, 5.6, 7.6, 0.45
    ax.add_patch(mpatches.Rectangle((bar_x, bar_y), bar_w, bar_h,
                                    linewidth=1, edgecolor="#bdc3c7", facecolor="#ecf0f1"))
    if received:
        fill_w = bar_w * len(received) / TOTAL
        ax.add_patch(mpatches.Rectangle((bar_x, bar_y), fill_w, bar_h,
                                        facecolor="#27ae60", alpha=0.85))
    ax.text(5.0, 5.35, f"len(buffers) == total_chunks ({TOTAL}) ?",
            ha="center", fontsize=9, color="#7f8c8d")

    # Bottom panel: current action
    panel = mpatches.FancyBboxPatch(
        (0.6, 0.5), 8.8, 4.5,
        boxstyle="round,pad=0.03,rounding_size=0.12",
        linewidth=1.5, edgecolor="#34495e", facecolor="#fafafa",
    )
    ax.add_patch(panel)

    if step < TOTAL:
        cid = step
        lines = [
            f"Data 受信: content_id={CONTENT_ID}, chunk_id={cid}, total_chunks={TOTAL}",
            f"buffers[{CONTENT_ID}][{cid}] = data  (256 B)",
            f"Got chunk {cid + 1}/{TOTAL}",
        ]
        if cid + 1 < TOTAL:
            lines.append("→ 次の chunk を待機...")
        else:
            lines.append("→ 全 chunk 到着!")
        title = f"Step {step + 1}: chunk {cid} 受信"
        title_color = COLORS[cid]
    elif step == TOTAL:
        title = "Step 5: 再構成 (Reassemble)"
        title_color = "#27ae60"
        lines = [
            "All chunks received! Reassembling...",
            f"full = b''.join(buffers[{CONTENT_ID}][i] for i in range({TOTAL}))",
            f"→ {TOTAL} × {CHUNK_SIZE} B = {TOTAL * CHUNK_SIZE} B",
        ]
    else:
        title = "Step 6: 保存 & 検証"
        title_color = "#8e44ad"
        lines = [
            f"save → received_image/image{CONTENT_ID}.png",
            f"MD5 = {MD5[:16]}...",
            "MD5 一致 → E2E 成功",
        ]

    ax.text(1.0, 4.5, title, fontsize=11, fontweight="bold", color=title_color)
    for i, line in enumerate(lines):
        ax.text(1.0, 3.8 - i * 0.55, line, fontsize=9, color="#2c3e50")

    # Reassembly strip on reassemble / done steps
    if step >= TOTAL:
        strip_y = 1.2
        strip_x = 1.0
        piece_w = 1.7
        for i in range(TOTAL):
            ax.add_patch(mpatches.Rectangle(
                (strip_x + i * piece_w, strip_y), piece_w - 0.05, 0.7,
                facecolor=COLORS[i], edgecolor="white", linewidth=1.5,
            ))
            ax.text(strip_x + i * piece_w + (piece_w - 0.05) / 2, strip_y + 0.35,
                    str(i), ha="center", va="center", fontsize=9,
                    color="white", fontweight="bold")
        ax.text(5.0, 0.75, "chunk_id 順に連結 → 元画像復元",
                ha="center", fontsize=9, color="#555")

    # Arrow animation for incoming chunk
    if step < TOTAL:
        arrow_y = 7.4
        ax.annotate(
            "", xy=(start_x + step * 2.0 + slot_w / 2, y_slots + slot_h + 0.05),
            xytext=(start_x + step * 2.0 + slot_w / 2, arrow_y + 0.8),
            arrowprops=dict(arrowstyle="-|>", color=COLORS[step], lw=2.5),
        )
        ax.text(start_x + step * 2.0 + slot_w / 2, arrow_y + 1.0, "Data",
                ha="center", fontsize=9, color=COLORS[step], fontweight="bold")


def build_frames():
    sequence = []
    for s in range(TOTAL):
        for _ in range(HOLD):
            sequence.append((s, set(range(s + 1))))
    for _ in range(HOLD):
        sequence.append((TOTAL, set(range(TOTAL))))
    for _ in range(HOLD * 2):
        sequence.append((TOTAL + 1, set(range(TOTAL))))
    return sequence


def main():
    fig, ax = plt.subplots(figsize=(9, 6.5))
    frames = build_frames()

    def update(idx):
        step, received = frames[idx]
        draw_frame(ax, step, received)
        return []

    anim = animation.FuncAnimation(
        fig, update, frames=len(frames), interval=350, blit=False, repeat=True,
    )
    anim.save(OUT, writer="pillow", dpi=100)
    plt.close(fig)
    print(f"Wrote {OUT} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
