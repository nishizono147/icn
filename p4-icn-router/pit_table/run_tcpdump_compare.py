#!/usr/bin/env python3
import os
import re
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

    print("trial,scapy_ms,tcpdump_ms,delta_ms")
    for trial in range(1, 11):
        pcap = f"/tmp/trial{trial}.pcap"
        h1.cmd(f"rm -f {pcap}")
        # Capture Data (0x88b6) while sending Interest
        cap = h1.cmd(
            f"bash -c 'tcpdump -i eth0 -w {pcap} ether proto 0x88b6 & "
            f"TP=$!; sleep 0.05; "
            f"python3 measure_scapy_once.py 1; "
            f"sleep 0.3; kill $TP 2>/dev/null; wait $TP 2>/dev/null'"
        )
        scapy_ms = cap.strip().splitlines()[0] if cap.strip() else ""
        dump = h1.cmd(f"tcpdump -ttt -n -r {pcap} 2>/dev/null | head -1")
        tcpdump_ms = ""
        if dump.strip():
            m = re.match(r"\s*([\d.]+)", dump)
            if m:
                tcpdump_ms = f"{float(m.group(1)) * 1000:.3f}"

        delta = ""
        if scapy_ms and tcpdump_ms:
            try:
                delta = f"{float(scapy_ms) - float(tcpdump_ms):.3f}"
            except ValueError:
                pass
        print(f"{trial},{scapy_ms},{tcpdump_ms},{delta}")
        time.sleep(0.2)

    net.stop()


if __name__ == "__main__":
    main()
