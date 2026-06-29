#!/usr/bin/env python3
"""Run chunk_table ICN vs IP baseline benchmarks and plot trial latency curves.

Both systems request content_id=4 (image4.png, 1024B = 4 x 256B chunks).
Metric: time from request/Interest to last chunk received.
"""
import argparse
import csv
import os
import statistics
import subprocess
import sys
import time

import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP", "Noto Sans CJK", "IPAGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = os.path.dirname(os.path.abspath(__file__))
CHUNK_DIR = os.path.join(ROOT, "chunk_table")
IP_DIR = os.path.join(ROOT, "ip_baseline")
UTILS = os.path.join(ROOT, "../utils")
CONTENT_ID = 4
CHUNK_SIZE = 256

sys.path.insert(0, UTILS)
from run_exercise import ExerciseRunner  # noqa: E402


def build_projects():
    for d in (CHUNK_DIR, IP_DIR):
        subprocess.run(["make", "build"], cwd=d, check=True)


def parse_benchmark_output(text):
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("trial,") or line.startswith("---"):
            continue
        parts = line.split(",")
        if len(parts) == 3:
            trial_s, lat_s, status = parts[0], parts[1], parts[2]
        elif len(parts) >= 4:
            trial_s, lat_s, status = parts[0], parts[2], parts[3]
        else:
            continue
        if status != "ok" or not lat_s:
            continue
        rows.append((int(trial_s), float(lat_s)))
    rows.sort(key=lambda x: x[0])
    return rows


def run_one_session(project_dir, bench_cmd, producer_cmd, log_prefix, producer_wait=2.5):
    prev_cwd = os.getcwd()
    os.chdir(project_dir)
    runner = ExerciseRunner(
        "topology.json",
        f"logs_{log_prefix}",
        f"pcaps_{log_prefix}",
        "build/switch.json",
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
        time.sleep(producer_wait)
        out = h1.cmd(bench_cmd)
        return parse_benchmark_output(out)
    finally:
        net.stop()
        os.chdir(prev_cwd)


def collect_sessions(label, project_dir, sessions, trials, interval, producer_cmd, bench_script):
    all_sessions = []
    bench_cmd = f"python3 {bench_script} {CONTENT_ID} -n {trials} -i {interval}"
    for s in range(1, sessions + 1):
        print(f"\n=== {label} session {s}/{sessions} ===", flush=True)
        rows = run_one_session(
            project_dir,
            bench_cmd,
            producer_cmd,
            log_prefix=f"{label.lower()}_s{s}",
        )
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
    if report_sessions > run_sessions:
        raise ValueError("report_sessions must be <= run_sessions")
    if report_sessions == run_sessions:
        return all_sessions, list(range(1, run_sessions + 1))
    drop = (run_sessions - report_sessions) // 2
    end = run_sessions - drop
    indices = list(range(drop + 1, end + 1))
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
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


def plot_graph(out_path, trials, icn_mean, ip_mean, sessions):
    x = list(range(1, trials + 1))
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        x, icn_mean, marker="o", linewidth=2,
        label=f"ICN (chunk_table, image4, N={sessions} sessions)",
        color="#1f77b4",
    )
    ax.plot(
        x, ip_mean, marker="s", linewidth=2,
        label=f"IP/UDP baseline (image4, N={sessions} sessions)",
        color="#ff7f0e",
    )
    ax.set_xlabel("要求回数")
    ax.set_ylabel("コンテンツ取得時間 (ms)")
    ax.set_title(
        f"chunk_table vs IP: image4.png ({CHUNK_SIZE}B/chunk, 10 requests)"
    )
    ax.set_xticks(x)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot: {out_path}")


def print_summary(trials, icn_mean, icn_std, ip_mean, ip_std):
    print("\n=== Summary (mean +/- std, ms) ===")
    print("trial,ICN_mean,ICN_std,IP_mean,IP_std,ICN_faster")
    icn_all, ip_all = [], []
    for i in range(trials):
        faster = ""
        if icn_mean[i] == icn_mean[i] and ip_mean[i] == ip_mean[i]:
            faster = "yes" if icn_mean[i] < ip_mean[i] else "no"
            icn_all.append(icn_mean[i])
            ip_all.append(ip_mean[i])
        print(
            f"{i+1},"
            f"{icn_mean[i]:.3f},{icn_std[i]:.3f},"
            f"{ip_mean[i]:.3f},{ip_std[i]:.3f},{faster}"
        )
    if icn_all and ip_all:
        print(
            f"\nOverall avg (trial 1-{trials}): "
            f"ICN={statistics.mean(icn_all):.2f} ms, "
            f"IP={statistics.mean(ip_all):.2f} ms"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Compare chunk_table ICN vs IP on image4 (multi-chunk)."
    )
    parser.add_argument("-n", "--trials", type=int, default=10)
    parser.add_argument("-s", "--sessions", type=int, default=12)
    parser.add_argument("--report-sessions", type=int, default=10)
    parser.add_argument("-i", "--interval", type=float, default=0.2)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--csv", default=os.path.join(ROOT, "results", "compare_chunk_ip.csv"),
    )
    parser.add_argument(
        "--png", default=os.path.join(ROOT, "results", "compare_chunk_ip.png"),
    )
    args = parser.parse_args()

    if args.report_sessions > args.sessions:
        parser.error("report-sessions must be <= sessions")
    if (args.sessions - args.report_sessions) % 2 != 0:
        parser.error("sessions - report-sessions must be even")

    if os.geteuid() != 0:
        print("Use: sudo python3 run_compare_chunk_graph.py", file=sys.stderr)
        sys.exit(1)

    if not args.skip_build:
        print("Building chunk_table and ip_baseline...")
        build_projects()

    icn_sessions = collect_sessions(
        "ICN", CHUNK_DIR, args.sessions, args.trials, args.interval,
        "python3 send_content.py --quiet", "benchmark_icn.py",
    )
    ip_sessions = collect_sessions(
        "IP", IP_DIR, args.sessions, args.trials, args.interval,
        "python3 serve_content_chunk.py --quiet", "benchmark_ip_chunk.py",
    )

    icn_report, icn_used = select_report_sessions(
        icn_sessions, args.sessions, args.report_sessions
    )
    ip_report, ip_used = select_report_sessions(
        ip_sessions, args.sessions, args.report_sessions
    )
    icn_mean, icn_std, _ = aggregate_by_trial(icn_report, args.trials)
    ip_mean, ip_std, _ = aggregate_by_trial(ip_report, args.trials)

    save_csv(args.csv, icn_sessions, ip_sessions, args.trials, icn_used, ip_used)
    print(f"Saved CSV: {args.csv}")
    print(f"Graph uses middle {args.report_sessions} sessions "
          f"(ICN: {icn_used}, IP: {ip_used})")
    print_summary(args.trials, icn_mean, icn_std, ip_mean, ip_std)
    plot_graph(args.png, args.trials, icn_mean, ip_mean, args.report_sessions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
