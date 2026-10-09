#!/usr/bin/env python3
"""run_compare_chunk_methods.py の結果（*_raw.csv）から、方式ごとの取得時間をグラフにする。

チャンク数ごとに 1 つのパネルを並べ、横軸は要求回数、縦軸は取得時間（平均、帯は ± 標準偏差）。
横軸の下段には、その要求で Data を返した場所（MCD のキャッシュ位置）を書く。

  python3 plot_compare_chunk_methods.py \
      --panel "4 チャンク (1 KB):results/compare_chunk_methods_raw.csv" \
      --panel "10 チャンク (2.5 KB):results/compare_chunk_methods_c10_raw.csv" \
      --out results/compare_chunk_methods.png
"""
import argparse
import csv
import os
import statistics
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

try:  # 日本語フォント（pip install matplotlib-fontja）
    import matplotlib_fontja  # noqa: F401,E402
except ImportError:
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK JP", "IPAexGothic", "DejaVu Sans"]

ROOT = os.path.dirname(os.path.abspath(__file__))

# 色は役割で固定（方式ごと。パネルが変わっても同じ方式は同じ色）
SERIES = {
    "table": {"label": "chunk_table（Interest 1 本）", "color": "#2a78d6", "marker": "o"},
    "pull-burst": {"label": "chunk_pull（残りをまとめて送る）", "color": "#eb6834", "marker": "s"},
    "pull-sequential": {"label": "chunk_pull（1 つずつ送る）", "color": "#1baf7a", "marker": "^"},
}
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"


def load(path, systems):
    """{system: {trial: [latency_ms, ...]}} と、試行ごとの返す場所を返す。"""
    data = defaultdict(lambda: defaultdict(list))
    source = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["system"] not in systems or r["status"] != "ok":
                continue
            t = int(r["trial"])
            data[r["system"]][t].append(float(r["latency_ms"]))
            source[t] = r["expected_source"]
    return data, source


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--panel", action="append", required=True,
                        help="'見出し:raw.csv のパス'（複数指定でパネルを横に並べる）")
    parser.add_argument("--systems", default="table,pull-burst")
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "compare_chunk_methods.png"))
    args = parser.parse_args()

    systems = [s.strip() for s in args.systems.split(",")]
    panels = []
    for p in args.panel:
        title, path = p.split(":", 1)
        if not os.path.isabs(path):
            path = os.path.join(ROOT, path)
        panels.append((title, *load(path, systems)))

    fig, axes = plt.subplots(1, len(panels), figsize=(max(5.6 * len(panels), 9.0), 4.8),
                             sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    ymax = 0.0
    sessions = set()

    for ax, (title, data, source) in zip(axes[0], panels):
        ax.set_facecolor(SURFACE)
        trials = sorted(source)
        for system in systems:
            spec = SERIES[system]
            means = [statistics.mean(data[system][t]) for t in trials]
            stds = [statistics.stdev(data[system][t]) if len(data[system][t]) > 1 else 0.0
                    for t in trials]
            sessions.update(len(data[system][t]) for t in trials)
            ymax = max(ymax, max(m + s for m, s in zip(means, stds)))
            ax.fill_between(trials, [m - s for m, s in zip(means, stds)],
                            [m + s for m, s in zip(means, stds)],
                            color=spec["color"], alpha=0.15, linewidth=0)
            ax.plot(trials, means, color=spec["color"], linewidth=2, marker=spec["marker"],
                    markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5,
                    label=spec["label"])
            # 値は 1 回目（h2 から返す）と最後の要求だけに付ける
            for t, m in ((trials[0], means[0]), (trials[-1], means[-1])):
                ax.annotate(f"{m:.1f}", (t, m), textcoords="offset points",
                            xytext=(0, 9 if system == systems[0] else -15),
                            ha="center", fontsize=8, color=TEXT_SECONDARY)

        ax.set_title(title, fontsize=11, color=TEXT, loc="left")
        ax.set_xticks(trials)
        ax.set_xticklabels([f"{t}\n{source[t]}" for t in trials], fontsize=8, color=TEXT_SECONDARY)
        ax.set_xlabel("要求回数（下段: Data を返した場所）", fontsize=9, color=TEXT_SECONDARY)
        ax.grid(True, axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(MUTED)
        ax.tick_params(colors=MUTED, labelcolor=TEXT_SECONDARY)

    axes[0][0].set_ylabel("コンテンツ取得時間 (ms)", fontsize=9, color=TEXT_SECONDARY)
    axes[0][0].set_ylim(0, ymax * 1.15)

    handles, labels = axes[0][0].get_legend_handles_labels()
    n = "/".join(str(x) for x in sorted(sessions))
    fig.suptitle("chunk_table と chunk_pull の取得時間（256 B/チャンク、"
                 f"各 {n} セッションの平均、帯は ± 標準偏差）",
                 fontsize=11, color=TEXT, x=0.01, ha="left", y=0.99)
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.01, 0.955), ncol=len(systems),
               frameon=False, fontsize=9, labelcolor=TEXT)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150, facecolor=SURFACE)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
