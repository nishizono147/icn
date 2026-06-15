#!/usr/bin/env python3
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
    h2.cmd(
        "python3 -c 'import sys; sys.path.insert(0,\".\"); "
        "from scapy.all import sniff; from icn_header import icn; "
        "open(\"/tmp/h2_interest_count\",\"w\").write(\"0\"); "
        "def cb(p):\n"
        "  import icn_header\n"
        "  if icn in p:\n"
        "    n=int(open(\"/tmp/h2_interest_count\").read() or 0)+1\n"
        "    open(\"/tmp/h2_interest_count\",\"w\").write(str(n))\n"
        "sniff(iface=\"eth0\", prn=cb)' &"
    )
    time.sleep(0.5)

    print("trial,latency_ms,h2_interest_total")
    for trial in range(1, 11):
        ms = h1.cmd("python3 measure_one.py 1 -n 1").strip().splitlines()[-1]
        count = h2.cmd("cat /tmp/h2_interest_count").strip()
        lat = ms.split(",")[-1] if "," in ms else ms
        print(f"{trial},{lat},{count}")

    net.stop()


if __name__ == "__main__":
    main()
