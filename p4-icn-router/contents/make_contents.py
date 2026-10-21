#!/usr/bin/env python3
"""計測用のコンテンツ content1.bin 〜 content10.bin を作る。

contentN.bin は N チャンク（256 B × N）の乱数で、random.Random(N) で作る。
同じ N なら何度作っても同じバイト列になる。
chunk_table と chunk_pull の Producer は、content_id N に contentN.bin を返す。
"""
import os
import random

CHUNK_SIZE = 256
HERE = os.path.dirname(os.path.abspath(__file__))

for n in range(1, 11):
    path = os.path.join(HERE, f"content{n}.bin")
    with open(path, "wb") as f:
        f.write(random.Random(n).randbytes(CHUNK_SIZE * n))
    print(f"{path}: {CHUNK_SIZE * n} B ({n} チャンク)")
