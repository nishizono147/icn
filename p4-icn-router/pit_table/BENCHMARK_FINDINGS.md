# ICN benchmark experiment findings

## Reproduction

Run: `sudo python3 run_cache_before_after.py`

Example output (representative run):

```
trial,latency_ms,pre_s1,pre_s2,pre_s3,serve_at,post_s1,post_s2,post_s3
1,51.974,False,False,False,h2,False,False,True,h2_total=1
2,27.986,False,False,True,s3,False,True,False,h2_total=1
3,55.972,False,True,False,s2,True,True,True,h2_total=1
4,22.989,True,True,True,s1,True,True,True,h2_total=1
5,68.965,True,True,True,s1,True,True,True,h2_total=1
8,82.958,True,True,True,s1,True,True,True,h2_total=1
```

## Root causes

### 1. Trials 1-3 decreasing latency (expected)

`switch.p4` behavior:

- On first Data return from h2, only the first switch (s3) caches because
  `cache_content()` sets `flag=0` before forwarding downstream.
- On cache hit at non-edge switches, cache is deleted after serving.
- Cache therefore migrates: h2 -> s3 -> s2 -> s1 over successive trials.

### 2. Trials 4+ spikes are NOT cold fetches

`BENCH_LOG=1` on h2 shows **only 1 Interest reaches h2 in all 10 trials**
(the first cold fetch). Slow trials 5/8/10 still have `h2_total=1`.

So post-warmup spikes are **not** caused by Interest reaching the producer again.

### 3. Spikes with s1 cache present = measurement jitter

When `pre_s1=True` (s1 should serve locally), latency still ranges ~7-83 ms.
Only one Data packet arrives per trial (`diag_benchmark.py`).

Conclusion: **Scapy AsyncSniffer userspace callback timing** adds large variable
delay unrelated to ICN path length. This matches "trial 6+ jumps and varies"
reported by user (spikes appear throughout warm phase, not only trial 6).

### 4. switch.p4 contributes to confusing warm-up (not the spike itself)

- Non-edge cache deletion causes multi-trial warm-up instead of immediate s1 hit.
- After several trials, CLI shows cache on s1/s2/s3 simultaneously due to
  repeated Data flows with `flag=1`.

## Recommendations

1. Measure with **pcap/tcpdump timestamps** on h1, not Scapy sniff callbacks.
2. Keep one long-running capture process (avoid per-trial sniffer start/stop).
3. For fair ICN evaluation, optionally fix `switch.p4` to cache on all switches
   on Data return and retain edge cache only at s1.
