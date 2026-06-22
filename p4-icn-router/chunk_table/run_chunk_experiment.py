#!/usr/bin/env python3
"""Verify chunk_table: multi-chunk image4, switch cache, cache-hit delivery."""
import hashlib
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../utils"))
from run_exercise import ExerciseRunner  # noqa: E402

CONTENT_ID = 4
CHUNK_SIZE = 256
IMAGE_PATH = "image4.png"


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


def chunk_cached(net, sw_name, content_id, chunk_id):
    idx = content_id * 10 + chunk_id
    val = reg_read(net, sw_name, "MyIngress.content_cache", idx)
    return val not in ("0", "?", "")


def total_chunks_cached(net, sw_name, content_id):
    val = reg_read(net, sw_name, "MyIngress.total_chunks_reg", content_id)
    try:
        return int(val)
    except ValueError:
        return 0


def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def wait_for_log(host, log_path, pattern, timeout=15.0, poll=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = host.cmd(f"grep -c '{pattern}' {log_path} 2>/dev/null || echo 0").strip()
        if count.isdigit() and int(count) > 0:
            return int(count)
        time.sleep(poll)
    return 0


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    expected_chunks = (os.path.getsize(IMAGE_PATH) + CHUNK_SIZE - 1) // CHUNK_SIZE
    original_md5 = file_md5(IMAGE_PATH)
    print(f"image4.png: {os.path.getsize(IMAGE_PATH)} bytes -> {expected_chunks} chunks")
    print(f"original md5: {original_md5}")

    subprocess.run(["make", "build"], check=True)

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

    h1.cmd("rm -rf received_image /tmp/h1_receive.log /tmp/h1_phase2.log")
    h2.cmd("rm -f /tmp/h2_content.log")

    h2.cmd("PYTHONUNBUFFERED=1 python3 send_content.py > /tmp/h2_content.log 2>&1 &")
    h1.cmd("PYTHONUNBUFFERED=1 python3 receive.py > /tmp/h1_receive.log 2>&1 &")
    time.sleep(1)

    results = {"pass": True, "checks": []}

    def check(name, ok, detail=""):
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))
        results["checks"].append((name, ok, detail))
        if not ok:
            results["pass"] = False

    # --- Phase 1: cold cache ---
    print("\n=== Phase 1: cold cache (Interest -> h2, multi-chunk Data) ===")
    h1.cmd("python3 send_interest.py 4")

    recon_count = wait_for_log(h1, "/tmp/h1_receive.log", "Successfully reconstructed", timeout=20)
    check("h1 received and reassembled all chunks (phase 1)", recon_count >= 1,
          f"reconstruct events={recon_count}")

    h2_interests = wait_for_log(h2, "/tmp/h2_content.log", "got a packet", timeout=10)
    check("h2 received Interest on cold fetch", h2_interests >= 1,
          f"interest events={h2_interests}")

    received_path = f"received_image/image{CONTENT_ID}.png"
    received_exists = h1.cmd(f"test -f {received_path} && echo yes || echo no").strip() == "yes"
    check("received image file exists (phase 1)", received_exists, received_path)

    if received_exists:
        h1.cmd(f"cp {received_path} /tmp/received_phase1.png")
        received_md5 = file_md5("/tmp/received_phase1.png") if os.path.exists("/tmp/received_phase1.png") else None
        # read via h1 since file is in mininet namespace - use md5 on h1
        recv_md5 = h1.cmd(f"md5sum {received_path} 2>/dev/null | awk '{{print $1}}'").strip()
        check("received image matches original (phase 1)", recv_md5 == original_md5,
              f"got={recv_md5}")

    print("\n  Switch cache after phase 1:")
    for sw in ("s1", "s2", "s3"):
        cached_chunks = sum(1 for i in range(expected_chunks) if chunk_cached(net, sw, CONTENT_ID, i))
        total_reg = total_chunks_cached(net, sw, CONTENT_ID)
        print(f"    {sw}: {cached_chunks}/{expected_chunks} chunks cached, total_chunks_reg={total_reg}")
        check(f"{sw} cached all {expected_chunks} chunks", cached_chunks == expected_chunks,
              f"{cached_chunks}/{expected_chunks}")
        check(f"{sw} total_chunks_reg == {expected_chunks}", total_reg == expected_chunks,
              f"reg={total_reg}")

    # --- Phase 2: warm cache (should be served from s1, not h2) ---
    print("\n=== Phase 2: warm cache (Interest hit at s1, multi-chunk from cache) ===")
    h2_interests_before = int(h2.cmd("grep -c 'got a packet' /tmp/h2_content.log 2>/dev/null || echo 0").strip())

    h1.cmd("pkill -f 'python3 receive.py' 2>/dev/null || true")
    time.sleep(0.5)
    h1.cmd("rm -f /tmp/h1_phase2.log")
    h1.cmd("PYTHONUNBUFFERED=1 python3 receive.py > /tmp/h1_phase2.log 2>&1 &")
    time.sleep(0.5)
    h1.cmd("python3 send_interest.py 4")

    recon2 = wait_for_log(h1, "/tmp/h1_phase2.log", "Successfully reconstructed", timeout=20)
    check("h1 received and reassembled all chunks (phase 2)", recon2 >= 1,
          f"reconstruct events={recon2}")

    h2_interests_after = int(h2.cmd("grep -c 'got a packet' /tmp/h2_content.log 2>/dev/null || echo 0").strip())
    check("h2 did NOT receive new Interest (served from cache)", h2_interests_after == h2_interests_before,
          f"before={h2_interests_before}, after={h2_interests_after}")

    recv2_md5 = h1.cmd(f"md5sum {received_path} 2>/dev/null | awk '{{print $1}}'").strip()
    check("received image matches original (phase 2)", recv2_md5 == original_md5,
          f"got={recv2_md5}")

    chunk_log = h1.cmd("grep 'Got chunk' /tmp/h1_phase2.log 2>/dev/null | wc -l").strip()
    check(f"h1 got {expected_chunks} chunk packets (phase 2)", chunk_log.isdigit() and int(chunk_log) == expected_chunks,
          f"chunk_lines={chunk_log}")

    print("\n=== Summary ===")
    passed = sum(1 for _, ok, _ in results["checks"] if ok)
    total = len(results["checks"])
    print(f"{passed}/{total} checks passed")
    if results["pass"]:
        print("OVERALL: PASS - chunk_table works for image4 (multi-chunk cache + delivery)")
    else:
        print("OVERALL: FAIL - see failed checks above")
        # dump logs for debugging
        print("\n--- h1 phase2 log (tail) ---")
        print(h1.cmd("tail -20 /tmp/h1_phase2.log 2>/dev/null"))
        print("\n--- s1 log (tail) ---")
        print(subprocess.run("tail -30 logs/s1.log", shell=True, capture_output=True, text=True).stdout)

    net.stop()
    return 0 if results["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
