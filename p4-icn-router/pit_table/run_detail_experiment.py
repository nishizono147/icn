#!/usr/bin/env python3
"""Run benchmark and print raw pcap timestamp deltas (microseconds)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
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
    h2.cmd("python3 send_content.py --quiet &")
    time.sleep(0.5)

    out = h1.cmd("python3 benchmark_icn.py 1 -n 10 -i 0.2 --pcap /tmp/bench_detail.pcap")
    print(out)

    print("=== raw pcap deltas (Interest -> Data) ===")
    print(h1.cmd("python3 analyze_pcap_deltas.py /tmp/bench_detail.pcap 1"))

    net.stop()


if __name__ == "__main__":
    main()
