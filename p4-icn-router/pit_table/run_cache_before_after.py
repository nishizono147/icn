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
            return line.split("=")[-1].strip()
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
    h2.cmd("rm -f /tmp/h2_interests.log")
    h2.cmd("BENCH_LOG=1 python3 send_content.py --quiet &")
    time.sleep(0.5)

    print("trial,latency_ms,pre_s1,pre_s2,pre_s3,serve_at,post_s1,post_s2,post_s3")
    for trial in range(1, 11):
        pre = {sw: cached(reg_read(net, sw, "MyIngress.content_cache", 1)) for sw in ("s1", "s2", "s3")}

        if pre["s1"]:
            serve_at = "s1"
        elif pre["s2"]:
            serve_at = "s2"
        elif pre["s3"]:
            serve_at = "s3"
        else:
            serve_at = "h2"

        out = h1.cmd("python3 measure_one.py 1 -n 1").strip()
        lat = out.splitlines()[-1].split(",")[-1]

        h2_count = h2.cmd("wc -l < /tmp/h2_interests.log 2>/dev/null || echo 0").strip()

        post = {sw: cached(reg_read(net, sw, "MyIngress.content_cache", 1)) for sw in ("s1", "s2", "s3")}
        print(
            f"{trial},{lat},{pre['s1']},{pre['s2']},{pre['s3']},{serve_at},"
            f"{post['s1']},{post['s2']},{post['s3']},h2_total={h2_count}"
        )
        time.sleep(0.25)

    net.stop()


if __name__ == "__main__":
    main()
