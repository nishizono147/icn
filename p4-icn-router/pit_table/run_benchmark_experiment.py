#!/usr/bin/env python3
"""Headless Mininet runner to reproduce benchmark_icn behavior."""
import json
import os
import subprocess
import sys
import time

from mininet.net import Mininet

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402


def read_register(sw_name, register_name, index, net, log_dir):
    sw = net.get(sw_name)
    cmd = (
        f"echo 'register_read {register_name} {index}' | "
        f"simple_switch_CLI --thrift-port {sw.thrift_port}"
    )
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=os.getcwd()
    )
    return result.stdout.strip()


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

    print("=== Starting producer on h2 ===")
    h2.cmd("python3 send_content.py --quiet > /tmp/send_content.log 2>&1 &")
    time.sleep(0.5)

    print("=== Running benchmark on h1 (10 trials) ===")
    out = h1.cmd("python3 benchmark_icn.py 1 -n 10 -i 0.2")
    print(out)

    print("=== Register state after benchmark (content_id=1) ===")
    for sw_name in ["s1", "s2", "s3"]:
        cache = read_register(sw_name, "MyIngress.content_cache", 1, net, "logs")
        pit = read_register(sw_name, "MyIngress.pit_table", 1, net, "logs")
        print(f"{sw_name} content_cache[1]: {cache}")
        print(f"{sw_name} pit_table[1]: {pit}")

    print("=== Producer log (last 20 lines) ===")
    print(h2.cmd("tail -20 /tmp/send_content.log"))

    net.stop()


if __name__ == "__main__":
    main()
