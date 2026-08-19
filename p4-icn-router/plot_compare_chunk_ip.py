#!/usr/bin/env python3
"""Plot chunk_table (ICN) vs IP baseline from compare_chunk_ip.csv."""
import argparse
import csv
import os
import statistics
from collections import defaultdict

import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP", "Noto Sans CJK", "IPAGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(ROOT, "results", "compare_chunk_ip.csv")
DEFAULT_PNG = os.path.join(ROOT, "results", "compare_chunk_ip.png")

COLOR_ICN = "#1f77b4"
COLOR_IP = "#d62728"


def load_trial_means(csv_path, trials=10):
    icn, ip = [], []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        rows = {int(row["trial"]): row for row in reader}
    for t in range(1, trials + 1):
        row = rows[t]
        icn.append(float(row["ICN"]))
        ip.append(float(row["IP"]))
    means = {"ICN": icn, "IP": ip}
    stds = {"ICN": [0.0] * trials, "IP": [0.0] * trials}
    return means, stds, {"ICN": [1] * trials, "IP": [1] * trials}, 1, 1


def load_trial_stats(csv_path, trials=10, included_only=True):
    buckets = {
        "ICN": defaultdict(list),
        "IP": defaultdict(list),
    }
    sessions = {"ICN": set(), "IP": set()}
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if included_only and row.get("included_in_graph") == "no":
                continue
            sys_name = row["system"]
            if sys_name not in buckets:
                continue
            lat_s = row["latency_ms"]
            if not lat_s:
                continue
            trial = int(row["trial"])
            if 1 <= trial <= trials:
                buckets[sys_name][trial].append(float(lat_s))
                sessions[sys_name].add(int(row["session"]))
    means, stds, ns = {}, {}, {}
    for sys_name in ("ICN", "IP"):
        m, s, n = [], [], []
        for t in range(1, trials + 1):
            vals = buckets[sys_name][t]
            if vals:
                m.append(statistics.mean(vals))
                s.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
                n.append(len(vals))
            else:
                m.append(float("nan"))
                s.append(0.0)
                n.append(0)
        means[sys_name], stds[sys_name], ns[sys_name] = m, s, n
    return means, stds, ns, len(sessions["ICN"]), len(sessions["IP"])


def plot_graph(out_path, means, stds, n_sessions_icn, n_sessions_ip, trials=10):
    x = list(range(1, trials + 1))
    icn, ip = means["ICN"], means["IP"]
    icn_std, ip_std = stds["ICN"], stds["IP"]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.fill_between(
        x,
        [a - b for a, b in zip(icn, icn_std)],
        [a + b for a, b in zip(icn, icn_std)],
        color=COLOR_ICN, alpha=0.15,
    )
    ax.fill_between(
        x,
        [a - b for a, b in zip(ip, ip_std)],
        [a + b for a, b in zip(ip, ip_std)],
        color=COLOR_IP, alpha=0.15,
    )
    icn_label = "ICN"
    ip_label = "IP/UDP"
    if n_sessions_icn > 1:
        icn_label += f" (N={n_sessions_icn} sessions)"
    if n_sessions_ip > 1:
        ip_label += f" (N={n_sessions_ip} sessions)"
    ax.plot(
        x, icn, marker="o", linewidth=2.5, markersize=7,
        color=COLOR_ICN, label=icn_label,
    )
    ax.plot(
        x, ip, marker="s", linewidth=2.5, markersize=7,
        color=COLOR_IP, label=ip_label,
    )

    for xi, yi in zip(x, icn):
        if yi == yi:
            ax.annotate(
                f"{yi:.1f}", (xi, yi), textcoords="offset points",
                xytext=(0, 10), ha="center", fontsize=7, color=COLOR_ICN,
            )
    for xi, yi in zip(x, ip):
        if yi == yi:
            ax.annotate(
                f"{yi:.1f}", (xi, yi), textcoords="offset points",
                xytext=(0, -14), ha="center", fontsize=7, color=COLOR_IP,
            )

    ax.set_xlabel("要求回数", fontsize=11)
    ax.set_ylabel("コンテンツ取得時間 (ms)", fontsize=11)
    ax.set_title(
        "ICN vs IP (256B × 4 chunks)",
        fontsize=15, fontweight="bold",
    )
    ax.set_xticks(x)
    ax.grid(True, alpha=0.35, linestyle="--")
    ax.legend(
        loc="upper right",
        fontsize=14,
        markerscale=1.6,
        handlelength=2.5,
        handletextpad=0.8,
        borderpad=0.9,
        labelspacing=0.7,
    )

    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot: {out_path}")


def print_summary(means, stds, ns):
    print("trial,ICN_mean,ICN_std,IP_mean,IP_std,ICN_faster")
    for i in range(len(means["ICN"])):
        im, is_, pm, ps = (
            means["ICN"][i], stds["ICN"][i],
            means["IP"][i], stds["IP"][i],
        )
        faster = "yes" if im < pm else "no"
        print(f"{i+1},{im:.3f},{is_:.3f},{pm:.3f},{ps:.3f},{faster}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument(
        "--means-csv",
        help="CSV with columns trial,ICN,IP (per-trial means, no std band)",
    )
    parser.add_argument("--png", default=DEFAULT_PNG)
    parser.add_argument("-n", "--trials", type=int, default=10)
    args = parser.parse_args()

    if args.means_csv:
        means, stds, ns, n_icn, n_ip = load_trial_means(args.means_csv, args.trials)
    else:
        means, stds, ns, n_icn, n_ip = load_trial_stats(args.csv, args.trials)
    print_summary(means, stds, ns)
    plot_graph(args.png, means, stds, n_icn, n_ip, args.trials)


if __name__ == "__main__":
    main()
