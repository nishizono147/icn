#!/usr/bin/env python3
"""Run benchmark and correlate latency with whether Interest reached h2."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    trials = 10

    runner = ExerciseRunner(
        "topology.json", "logs", "pcaps", "build/switch.json",
        bmv2_exe="simple_switch_grpc", quiet=True,
    )
    runner.create_network()
    net = runner.net
    net.start()
    time.sleep(1)
    runner.program_hosts()
    runner.program_switches()
    time.sleep(2)

    h1 = net.get("h1")
    h2 = net.get("h2")

    h2.cmd("python3 send_content.py --quiet > /tmp/send_content.log 2>&1 &")
    time.sleep(0.5)

    # Log each Interest arrival at h2 with timestamp
    h2.cmd(
        "python3 -c '"
        "import time, sys\n"
        "sys.path.insert(0,\".\")\n"
        "from scapy.all import sniff\n"
        "from icn_header import icn\n"
        "open(\"/tmp/h2_interests.tsv\",\"w\").write(\"ts\\tcontent_id\\n\")\n"
        "def cb(p):\n"
        "  if icn in p:\n"
        "    open(\"/tmp/h2_interests.tsv\",\"a\").write(f\"{time.time()}\\t{p[icn].content_id}\\n\")\n"
        "sniff(iface=\"eth0\", prn=cb)' > /tmp/h2_sniff.log 2>&1 &"
    )
    time.sleep(0.5)

    t0 = time.time()
    out = h1.cmd(f"python3 benchmark_icn.py 1 -n {trials} -i 0.2")
    t1 = time.time()
    print(out)
    print(f"=== wall clock: {t1 - t0:.2f}s ===")

    interests = h2.cmd("cat /tmp/h2_interests.tsv")
    print("=== h2 Interest arrivals ===")
    print(interests if interests.strip() else "(none)")

    lines = [l for l in out.splitlines() if re.match(r"^\d+,", l)]
    print("\n=== Analysis: warm latency vs expected path ===")
    print("trial,latency_ms,reached_h2_since_start")
    interest_times = []
    for row in interests.strip().splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) == 2:
            interest_times.append(float(parts[0]))

    benchmark_start = t0 + 1.0  # approximate after setup
    for line in lines:
        trial, phase, lat, status = line.split(",")
        if status != "ok" or not lat:
            print(f"{trial},{lat or 'timeout'},?,{status}")
            continue
        # count h2 interests before end of this trial (rough: trial * avg interval)
        trial_idx = int(trial)
        approx_end = benchmark_start + trial_idx * 0.25
        reached = sum(1 for ts in interest_times if ts <= approx_end)
        print(f"{trial},{lat},{reached},{status}")

    net.stop()


if __name__ == "__main__":
    main()
