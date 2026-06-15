# IP baseline (comparison with pit_table)

Same topology (`h1-s1-s2-s3-h2`), hosts, PNG images, and payload size (256 B)
as `pit_table`. Uses P4 IPv4 forwarding (`switch.p4`) and **UDP request/response**
(instead of HTTP/TCP) for a fairer comparison with ICN Interest/Data.

## Protocol

| Direction | Format |
|-----------|--------|
| Request (h1→h2) | UDP port 9999: `content_id` (32b) + `flag` (8b) + `hop_count` (8b) |
| Response (h2→h1) | UDP port 9999: `content_id` (32b) + `flag` (8b) + `data` (256 B) |

Matches ICN field layout and image mapping (`image1.png` …).

## Start network

```bash
cd p4-icn-router/ip_baseline
make
```

## Run benchmark

```bash
# h2 (producer)
python3 serve_content.py --quiet

# h1 (consumer)
python3 benchmark_ip.py 1
```

## Compare with ICN

```bash
cd ../pit_table && python3 benchmark_icn.py 1   # ICN
cd ../ip_baseline && python3 benchmark_ip.py 1  # IP/UDP
```

## Research notes

- **Primary comparison:** ICN trial 1 (cold) vs IP trial 1 or all-trials average (both end-to-end to h2).
- **ICN warm trials** show in-network cache; IP has no equivalent — report separately.
- Measurement: tcpdump pcap timestamps (request → response), same method as `benchmark_icn.py`.
