#!/usr/bin/env python3
"""Plot chunk_table vs chunk_pull mean latency by request number."""
import csv
import os

import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP", "Noto Sans CJK", "IPAGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "results", "compare_chunk_table_pull.csv")
PNG_PATH = os.path.join(ROOT, "results", "compare_chunk_table_pull.png")

# Mean latency (ms) per trial — 10 sessions averaged
CHUNK_TABLE = [
    14.8884, 12.2754, 9.6242, 7.5547, 8.3474,
    7.7352, 7.055, 6.4506, 7.0693, 7.2758,
]
CHUNK_PULL = [
    2733.0, 2794.3, 2801.9, 2775.3, 2785.5,
    2774.0, 2804.1, 2776.7, 2786.6, 2807.2,
]

COLOR_TABLE = "#1f77b4"
COLOR_PULL = "#ff7f0e"


def save_csv(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trial", "chunk_table_ms", "chunk_pull_ms"])
        for i in range(10):
            w.writerow([i + 1, CHUNK_TABLE[i], CHUNK_PULL[i]])


def plot_graph(out_path):
    x = list(range(1, 11))
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=(8, 7), sharex=True,
        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.08},
    )

    # --- chunk_table (ms scale ~6–15) ---
    ax_top.plot(
        x, CHUNK_TABLE, marker="o", linewidth=2.5, markersize=7,
        color=COLOR_TABLE,
        label="chunk_table (1 Interest + clone/recirculate)",
    )
    ax_top.set_ylabel("取得時間 (ms)")
    ax_top.set_title(
        "chunk_table — MCD キャッシュで短縮",
        fontsize=11, loc="left", color=COLOR_TABLE, fontweight="bold",
    )
    ax_top.set_xticks(x)
    ax_top.grid(True, alpha=0.35, linestyle="--")
    ax_top.set_ylim(0, max(CHUNK_TABLE) * 1.35)
    for xi, yi in zip(x, CHUNK_TABLE):
        ax_top.annotate(
            f"{yi:.1f}", (xi, yi), textcoords="offset points",
            xytext=(0, 8), ha="center", fontsize=7, color=COLOR_TABLE,
        )

    # --- chunk_pull (ms scale ~2700–2800) ---
    ax_bot.plot(
        x, CHUNK_PULL, marker="s", linewidth=2.5, markersize=7,
        color=COLOR_PULL,
        label="chunk_pull (Method A: Interest × 4)",
    )
    ax_bot.set_xlabel("要求回数")
    ax_bot.set_ylabel("取得時間 (ms)")
    ax_bot.set_title(
        "chunk_pull — 要求ごとに Interest 4 本（約 2.7 s で横ばい）",
        fontsize=11, loc="left", color=COLOR_PULL, fontweight="bold",
    )
    ax_bot.set_xticks(x)
    ax_bot.grid(True, alpha=0.35, linestyle="--")
    y_min, y_max = min(CHUNK_PULL), max(CHUNK_PULL)
    margin = (y_max - y_min) * 0.4 or 50
    ax_bot.set_ylim(y_min - margin, y_max + margin)
    for xi, yi in zip(x, CHUNK_PULL):
        ax_bot.annotate(
            f"{yi:.0f}", (xi, yi), textcoords="offset points",
            xytext=(0, 8), ha="center", fontsize=7, color=COLOR_PULL,
        )

    fig.suptitle(
        "chunk_table vs chunk_pull: image4 (256 B × 4 chunks, 10 セッション平均)",
        fontsize=12, fontweight="bold", y=0.98,
    )

    # Overall speedup note
    avg_table = sum(CHUNK_TABLE) / len(CHUNK_TABLE)
    avg_pull = sum(CHUNK_PULL) / len(CHUNK_PULL)
    fig.text(
        0.5, 0.01,
        f"全試行平均: chunk_table {avg_table:.1f} ms  /  chunk_pull {avg_pull:.0f} ms"
        f"  （chunk_table は約 {avg_pull / avg_table:.0f} 倍速）",
        ha="center", fontsize=9, style="italic",
    )

    fig.subplots_adjust(top=0.90, bottom=0.08)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot: {out_path}")


def main():
    save_csv(CSV_PATH)
    print(f"Saved CSV: {CSV_PATH}")
    plot_graph(PNG_PATH)


if __name__ == "__main__":
    main()
