#!/usr/bin/env python3
"""Instrumented benchmark: log per-trial path (h2 Interest count) and latency."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    switch_json = "build/switch.json"

    runner = ExerciseRunner(
        "topology.json", "logs", "pcaps", switch_json,
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

    # Producer with Interest counter
    h2.cmd(
        "python3 -c \""
        "import os, sys\n"
        "from scapy.all import sniff\n"
        "sys.path.insert(0, '.')\n"
        "from icn_header import icn\n"
        "open('/tmp/h2_interest.log','w').close()\n"
        "def cb(p):\n"
        "  if icn in p:\n"
        "    with open('/tmp/h2_interest.log','a') as f:\n"
        "      f.write(f'{time.time()} content_id={p[icn].content_id}\\n')\n"
        "import time\n"
        "sniff(iface='eth0', prn=cb)\n"
        "\" > /tmp/producer.log 2>&1 &"
    )
    time.sleep(0.5)

    print("trial,latency_ms,h2_interests_this_trial,status")
    prev_count = 0
    for trial in range(1, 11):
        h2.cmd("echo TRIAL_START >> /tmp/h2_interest.log")
        out = h1.cmd(f"python3 benchmark_icn.py 1 -n 1 -i 0 -t 5 2>&1")
        m = re.search(r"1,cold,([\d.]+|),(\w+)", out.replace("warm", "cold"))
        if not m:
            m = re.search(r"1,\w+,([\d.]+|),(\w+)", out)
        latency = m.group(1) if m else "?"
        status = m.group(2) if m else "parse_error"

        log = h2.cmd("grep content_id /tmp/h2_interest.log | wc -l").strip()
        count = int(log) if log.isdigit() else 0
        h2_interests = count - prev_count
        prev_count = count

        print(f"{trial},{latency},{h2_interests},{status}")
        time.sleep(0.3)

    print("\n=== h2 interest log ===")
    print(h2.cmd("grep -v TRIAL_START /tmp/h2_interest.log"))

    net.stop()


if __name__ == "__main__":
    main()
