#!/usr/bin/env python3
"""Run ICN (pit_table) vs IP baseline benchmarks and plot trial latency curves.

Each session starts a fresh Mininet network so ICN trial 1 is always cold.
By default 12 sessions are run per system; the first and last are discarded
and statistics/plots use the middle 10 sessions.
"""
import argparse
import csv
import os
import statistics
import subprocess
import sys
import time

import matplotlib.pyplot as plt

# Japanese axis labels
plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP", "Noto Sans CJK", "IPAGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.abspath(__file__))
PIT_DIR = os.path.join(ROOT, "pit_table")
IP_DIR = os.path.join(ROOT, "ip_baseline")
UTILS = os.path.join(ROOT, "../utils")

sys.path.insert(0, UTILS)
from run_exercise import ExerciseRunner  # noqa: E402


def build_projects():
    for d in (PIT_DIR, IP_DIR):
        subprocess.run(["make", "build"], cwd=d, check=True)


def parse_benchmark_output(text):
    """Return list of (trial, latency_ms) for successful trials."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("trial,") or line.startswith("---"):
            continue
        parts = line.split(",")
        if len(parts) < 4:
            continue
        trial_s, _phase, lat_s, status = parts[0], parts[1], parts[2], parts[3]
        if status != "ok" or not lat_s:
            continue
        rows.append((int(trial_s), float(lat_s)))
    rows.sort(key=lambda x: x[0])
    return rows


def run_one_session(project_dir, bench_cmd, producer_cmd, log_prefix):
    prev_cwd = os.getcwd()
    os.chdir(project_dir)
    switch_json = "build/switch.json"
    runner = ExerciseRunner(
        "topology.json",
        f"logs_{log_prefix}",
        f"pcaps_{log_prefix}",
        switch_json,
        bmv2_exe="simple_switch_grpc",
        quiet=True,
    )
    runner.create_network()
    net = runner.net
    try:
        net.start()
        time.sleep(1)
        runner.program_hosts()
        runner.program_switches()
        time.sleep(2)

        h1 = net.get("h1")
        h2 = net.get("h2")
        h2.cmd(f"{producer_cmd} > /tmp/{log_prefix}_producer.log 2>&1 &")
        time.sleep(0.5)
        out = h1.cmd(bench_cmd)
        return parse_benchmark_output(out)
    finally:
        net.stop()
        os.chdir(prev_cwd)


def collect_sessions(label, project_dir, sessions, trials, interval, content_id, producer_cmd, bench_script):
    all_sessions = []
    bench_cmd = f"python3 {bench_script} {content_id} -n {trials} -i {interval}"
    for s in range(1, sessions + 1):
        print(f"\n=== {label} session {s}/{sessions} ===", flush=True)
        rows = run_one_session(
            project_dir,
            bench_cmd,
            producer_cmd,
            log_prefix=f"{label.lower()}_s{s}",
        )
        if len(rows) != trials:
            got = len(rows)
            print(f"WARNING: expected {trials} trials, got {got}", flush=True)
        latencies = [None] * trials
        for trial, lat in rows:
            if 1 <= trial <= trials:
                latencies[trial - 1] = lat
        all_sessions.append(latencies)
        ok = [x for x in latencies if x is not None]
        if ok:
            print(f"  trial1={latencies[0]:.2f}ms, last={ok[-1]:.2f}ms", flush=True)
        time.sleep(0.5)
    return all_sessions


def select_report_sessions(all_sessions, run_sessions, report_sessions):
    """Drop equal counts from both ends; e.g. 12 run -> middle 10."""
    if report_sessions > run_sessions:
        raise ValueError("report_sessions must be <= run_sessions")
    if report_sessions == run_sessions:
        return all_sessions, list(range(1, run_sessions + 1))
    drop = (run_sessions - report_sessions) // 2
    end = run_sessions - drop
    indices = list(range(drop + 1, end + 1))  # 1-based session numbers
    return all_sessions[drop:end], indices


def aggregate_by_trial(all_sessions, trials):
    means, stds, ns = [], [], []
    for t in range(trials):
        vals = [s[t] for s in all_sessions if s[t] is not None]
        if vals:
            means.append(statistics.mean(vals))
            stds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
            ns.append(len(vals))
        else:
            means.append(float("nan"))
            stds.append(0.0)
            ns.append(0)
    return means, stds, ns


def save_csv(path, icn_sessions, ip_sessions, trials, icn_used, ip_used):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    icn_used_set = set(icn_used)
    ip_used_set = set(ip_used)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["system", "session", "trial", "latency_ms", "included_in_graph"])
        for sys_name, sessions, used_set in (
            ("ICN", icn_sessions, icn_used_set),
            ("IP", ip_sessions, ip_used_set),
        ):
            for si, latencies in enumerate(sessions, start=1):
                included = si in used_set
                for ti, lat in enumerate(latencies, start=1):
                    w.writerow([
                        sys_name, si, ti,
                        "" if lat is None else f"{lat:.6f}",
                        "yes" if included else "no",
                    ])


def plot_graph(out_path, trials, icn_mean, icn_std, ip_mean, ip_std, sessions):
    x = list(range(1, trials + 1))
    fig, ax = plt.subplots(figsize=(8, 5))

    ax.plot(
        x, icn_mean, marker="o", linewidth=2,
        label=f"ICN (pit_table, N={sessions} sessions)",
        color="#1f77b4",
    )
    ax.plot(
        x, ip_mean, marker="s", linewidth=2,
        label=f"IP/UDP baseline (N={sessions} sessions)",
        color="#ff7f0e",
    )

    ax.set_xlabel("要求回数")
    ax.set_ylabel("コンテンツ取得時間 (ms)")
    ax.set_title("ICN vs IP: End-to-end content retrieval latency")
    ax.set_xticks(x)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot: {out_path}")


def print_summary(trials, icn_mean, icn_std, ip_mean, ip_std):
    print("\n=== Summary (mean +/- std, ms) ===")
    print("trial,ICN_mean,ICN_std,IP_mean,IP_std")
    for i in range(trials):
        print(
            f"{i+1},"
            f"{icn_mean[i]:.3f},{icn_std[i]:.3f},"
            f"{ip_mean[i]:.3f},{ip_std[i]:.3f}"
        )
    if icn_mean[0] == icn_mean[0] and ip_mean[0] == ip_mean[0]:
        print(f"\nCold (trial 1): ICN={icn_mean[0]:.2f} ms, IP={ip_mean[0]:.2f} ms")
    warm_icn = [icn_mean[i] for i in range(3, trials) if icn_mean[i] == icn_mean[i]]
    warm_ip = [ip_mean[i] for i in range(3, trials) if ip_mean[i] == ip_mean[i]]
    if warm_icn:
        print(f"ICN warm (trial 4-{trials}) avg: {statistics.mean(warm_icn):.2f} ms")
    if warm_ip:
        print(f"IP trial 4-{trials} avg: {statistics.mean(warm_ip):.2f} ms")


def load_sessions_from_csv(csv_path, trials):
    icn_sessions, ip_sessions = [], []
    by_key = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["system"], int(row["session"]))
            trial = int(row["trial"])
            lat = row["latency_ms"]
            val = float(lat) if lat else None
            if key not in by_key:
                by_key[key] = [None] * trials
            by_key[key][trial - 1] = val
    for key in sorted(by_key.keys()):
        if key[0] == "ICN":
            icn_sessions.append(by_key[key])
        else:
            ip_sessions.append(by_key[key])
    return icn_sessions, ip_sessions


def main():
    parser = argparse.ArgumentParser(description="Compare ICN vs IP benchmark and plot.")
    parser.add_argument("--content-id", type=int, default=1)
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-s", "--sessions", type=int, default=12,
                        help="Mininet sessions to run per system (default: 12)")
    parser.add_argument(
        "--report-sessions", type=int, default=10,
        help="Use middle N sessions for graph/stats (default: 10, drops ends)",
    )
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Regenerate PNG from existing CSV (no Mininet)",
    )
    parser.add_argument(
        "--out-dir", default=os.path.join(ROOT, "results"),
        help="Directory for CSV and PNG output",
    )
    args = parser.parse_args()

    if args.report_sessions > args.sessions:
        parser.error("report-sessions must be <= sessions")
    if (args.sessions - args.report_sessions) % 2 != 0:
        parser.error("sessions - report-sessions must be even (symmetric trim)")

    os.makedirs(args.out_dir, exist_ok=True)
    csv_path = os.path.join(args.out_dir, "compare_icn_ip.csv")
    png_path = os.path.join(args.out_dir, "compare_icn_ip.png")

    if args.plot_only:
        if not os.path.exists(csv_path):
            print(f"Missing {csv_path}", file=sys.stderr)
            sys.exit(1)
        icn_sessions, ip_sessions = load_sessions_from_csv(csv_path, args.trials)
        icn_report, icn_used = select_report_sessions(
            icn_sessions, len(icn_sessions), args.report_sessions
        )
        ip_report, ip_used = select_report_sessions(
            ip_sessions, len(ip_sessions), args.report_sessions
        )
        icn_mean, icn_std, _ = aggregate_by_trial(icn_report, args.trials)
        ip_mean, ip_std, _ = aggregate_by_trial(ip_report, args.trials)
        print(f"Using middle {args.report_sessions} sessions "
              f"(ICN: {icn_used}, IP: {ip_used})")
        print_summary(args.trials, icn_mean, icn_std, ip_mean, ip_std)
        plot_graph(
            png_path, args.trials, icn_mean, icn_std, ip_mean, ip_std,
            args.report_sessions,
        )
        return 0

    if os.geteuid() != 0:
        print("This script must run as root (Mininet). Use: sudo python3 run_compare_graph.py",
              file=sys.stderr)
        sys.exit(1)

    if not args.skip_build:
        print("Building pit_table and ip_baseline...")
        build_projects()

    icn_sessions = collect_sessions(
        "ICN", PIT_DIR, args.sessions, args.trials, args.interval,
        args.content_id, "python3 send_content.py --quiet", "benchmark_icn.py",
    )
    ip_sessions = collect_sessions(
        "IP", IP_DIR, args.sessions, args.trials, args.interval,
        args.content_id, "python3 serve_content.py --quiet", "benchmark_ip.py",
    )

    icn_report, icn_used = select_report_sessions(
        icn_sessions, args.sessions, args.report_sessions
    )
    ip_report, ip_used = select_report_sessions(
        ip_sessions, args.sessions, args.report_sessions
    )

    icn_mean, icn_std, _ = aggregate_by_trial(icn_report, args.trials)
    ip_mean, ip_std, _ = aggregate_by_trial(ip_report, args.trials)

    save_csv(csv_path, icn_sessions, ip_sessions, args.trials, icn_used, ip_used)
    print(f"Saved CSV: {csv_path}")
    print(f"Graph uses middle {args.report_sessions} sessions "
          f"(ICN: {icn_used}, IP: {ip_used})")

    print_summary(args.trials, icn_mean, icn_std, ip_mean, ip_std)
    plot_graph(
        png_path, args.trials, icn_mean, icn_std, ip_mean, ip_std,
        args.report_sessions,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
