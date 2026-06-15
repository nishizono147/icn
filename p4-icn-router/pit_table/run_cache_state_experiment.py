#!/usr/bin/env python3
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402


def reg_read(net, sw_name, reg, idx):
    sw = net.get(sw_name)
    cmd = (
        f"echo 'register_read {reg} {idx}' | "
        f"simple_switch_CLI --thrift-port {sw.thrift_port}"
    )
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f"{reg}[{idx}]" in line:
            val = line.split("=")[-1].strip()
            return val
    return "?"


def cached(val):
    return val not in ("0", "?", "")


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

    print("trial,latency_ms,s1_cache,s2_cache,s3_cache,path_guess")
    for trial in range(1, 11):
        out = h1.cmd("python3 measure_one.py 1 -n 1").strip()
        lat = out.splitlines()[-1].split(",")[-1]

        s1 = reg_read(net, "s1", "MyIngress.content_cache", 1)
        s2 = reg_read(net, "s2", "MyIngress.content_cache", 1)
        s3 = reg_read(net, "s3", "MyIngress.content_cache", 1)
        c1, c2, c3 = cached(s1), cached(s2), cached(s3)

        if c1:
            path = "s1_hit"
        elif c2:
            path = "s2_hit"
        elif c3:
            path = "s3_hit"
        else:
            path = "cold_h2"

        print(f"{trial},{lat},{c1},{c2},{c3},{path}")
        time.sleep(0.25)

    net.stop()


if __name__ == "__main__":
    main()
