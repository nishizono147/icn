#!/usr/bin/env python3
"""チャンク数ごとの取得時間をグラフにする（run_compare_chunk_methods.py の *_raw.csv から）。

横軸はチャンク数、縦軸は取得時間。Data を返した場所（h2・s3・s2・s1）ごとに 1 本の線にする。
s1 から返すのは 4〜10 回目なので、セッションごとにその平均を 1 つの値とする。
点はセッション間の平均。方式ごとに 1 つのパネルを並べる。

  python3 plot_chunk_sweep.py results/csv/chunk_sweep_pull_raw.csv --systems pull-burst \\
      --out results/png/chunk_sweep_pull.png
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

SYSTEM_TITLE = {
    "table": "chunk_table（Interest 1 本）",
    "pull-burst": "chunk_pull（残りをまとめて送る）",
    "pull-sequential": "chunk_pull（1 つずつ送る）",
}
# 返す場所は遠さの順なので、方式の色（plot_compare_chunk_methods.py と同じ）の濃さで表す。遠いほど濃い
RAMP = {
    "table": ["#123c70", "#1d5aa6", "#2a78d6", "#6fa5e6"],
    "pull-burst": ["#8a3412", "#c24e1f", "#eb6834", "#f29a6c"],
    "pull-sequential": ["#0b5c3f", "#13865b", "#1baf7a", "#6cc9a4"],
}
LOCATIONS = ["h2", "s3", "s2", "s1"]
LOCATION_LABEL = {"h2": "h2（Producer）", "s3": "s3", "s2": "s2", "s1": "s1（Consumer の隣）"}
MARKERS = {"h2": "D", "s3": "^", "s2": "s", "s1": "o"}
TEXT = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"


def load(path, systems):
    """{system: {location: {n_chunks: [セッションごとの値, ...]}}} を返す。"""
    per_session = defaultdict(list)  # (system, location, n, session) -> [latency_ms]
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["system"] not in systems or r["status"] != "ok":
                continue
            key = (r["system"], r["expected_source"], int(r["n_chunks"]), int(r["session"]))
            per_session[key].append(float(r["latency_ms"]))
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for (system, loc, n, _session), vals in per_session.items():
        data[system][loc][n].append(statistics.mean(vals))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw_csv")
    parser.add_argument("--systems", default="pull-burst", help="カンマ区切り。方式ごとに 1 パネル")
    parser.add_argument("--title", default="")
    parser.add_argument("--out", default=os.path.join(ROOT, "results", "png", "chunk_sweep.png"))
    args = parser.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    data = load(args.raw_csv, systems)

    fig, axes = plt.subplots(1, len(systems), figsize=(6.4 * len(systems), 5.0),
                             sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    ymax = 0.0
    sessions = set()

    for ax, system in zip(axes[0], systems):
        ax.set_facecolor(SURFACE)
        all_n = set()
        for i, loc in enumerate(LOCATIONS):
            series = data[system].get(loc)
            if not series:
                continue
            ns = sorted(series)
            all_n.update(ns)
            means = [statistics.mean(series[n]) for n in ns]
            sessions.update(len(series[n]) for n in ns)
            ymax = max(ymax, max(means))
            color = RAMP[system][i]
            ax.plot(ns, means, color=color, linewidth=2, marker=MARKERS[loc], markersize=6,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=LOCATION_LABEL[loc])
            # 線の右端に返す場所の名前を書く（色だけで見分けなくてよいように）
            ax.annotate(loc, (ns[-1], means[-1]), textcoords="offset points", xytext=(8, -3),
                        fontsize=9, color=TEXT_SECONDARY)

        ax.set_title(args.title or SYSTEM_TITLE.get(system, system), fontsize=11, color=TEXT, loc="left")
        ax.set_xticks(sorted(all_n))
        ax.set_xlabel("チャンク数（1 チャンク = 256 B）", fontsize=9, color=TEXT_SECONDARY)
        ax.grid(True, axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(MUTED)
        ax.tick_params(colors=MUTED, labelcolor=TEXT_SECONDARY)
        ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=TEXT)
        if all_n:
            ax.set_xlim(min(all_n) - 0.4, max(all_n) + 0.9)

    axes[0][0].set_ylabel("コンテンツ取得時間 (ms)", fontsize=9, color=TEXT_SECONDARY)
    axes[0][0].set_ylim(0, ymax * 1.25)
    n = "/".join(str(x) for x in sorted(sessions))
    fig.suptitle(f"チャンク数と取得時間（各 {n} セッションの平均）",
                 fontsize=11, color=TEXT, x=0.01, ha="left", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, dpi=150, facecolor=SURFACE)
    print(f"Saved: {args.out}")


if __name__ == "__main__":
    main()
