#!/usr/bin/env python3
"""Headless Mininet runner for ip_baseline benchmark."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    switch_json = "build/switch.json"
    if not os.path.exists(switch_json):
        print("Missing build/switch.json. Run 'make build' first.", file=sys.stderr)
        sys.exit(1)

    runner = ExerciseRunner(
        "topology.json",
        "logs",
        "pcaps",
        switch_json,
        bmv2_exe="simple_switch_grpc",
        quiet=True,
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

    print("=== Starting UDP server on h2 ===")
    h2.cmd("python3 serve_content.py --quiet > /tmp/serve_http.log 2>&1 &")
    time.sleep(0.5)

    print("=== Running IP benchmark on h1 ===")
    out = h1.cmd("python3 benchmark_ip.py 1 -n 10 -i 0.2")
    print(out)

    net.stop()


if __name__ == "__main__":
    main()
