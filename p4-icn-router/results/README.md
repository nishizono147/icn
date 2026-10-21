# 計測結果

## フォルダ

| フォルダ | 中身 |
|---|---|
| `csv/` | 計測の生データ（`*_raw.csv`、1 行 = 1 回の取得）と集計（`*_summary.csv`、方式・要求回数ごとの平均） |
| `png/` | グラフ |
| `log/` | 実行ログ |

同じ計測の CSV とグラフは、フォルダが違っても同じ名前で始まる
（例: `csv/compare_chunk_methods_delay5ms_raw.csv` と `png/compare_chunk_methods_delay5ms.png`）。
下の表のファイル名は、フォルダと `_raw.csv` などを省いて書いている。

計測の方法、CSV の列の意味、実験のコマンドは [../README.md](../README.md) を参照。主な数値もそちらにまとめている。

## コンテンツの番号（content_id）

chunk_table と chunk_pull の `content_id` の割り当ては 2026-10-21 に変えた。

| 期間 | 割り当て |
|---|---|
| 2026-10-21 より前 | `4` = `image4.png`（4 チャンク）、`6` = `content10.bin`（10 チャンク） |
| 2026-10-21 から | `N` = `contentN.bin`（N チャンク、N = 1〜10） |

`content10.bin` は変える前後で同じファイル（`random.Random(10)` で作った 2560 B）。
2026-10-21 より前の CSV には content_id の列がないので、どのコンテンツで測ったかは下の表で確認する。

## 今の計測（`run_compare_chunk_methods.py` + `consumer_bench.py`）

方式を同じ Consumer で交互に計測したもの。1 セッションで同じコンテンツを 10 回取得し、
返す場所は h2 → s3 → s2 → s1 × 7 と移る。

### 方式の比較（横軸 = 要求回数）

| 名前 | 計測した日 | 方式 | コンテンツ | リンクの遅延 | セッション | グラフ |
|---|---|---|---|---|---|---|
| `compare_chunk_methods` | 2026-10-03 | table、pull-sequential、pull-burst | 旧 4（4 チャンク） | なし | 20 | `compare_chunk_methods.png`（左） |
| `compare_chunk_methods_c10` | 2026-10-08 | table、pull-burst | 旧 6（10 チャンク） | なし | 20 | `compare_chunk_methods.png`（右） |
| `compare_chunk_methods_c10_run2` | 2026-10-09 | table、pull-burst | 旧 6（10 チャンク） | なし | 20 | `compare_chunk_methods_c10_run2.png` |
| `my_c10` | 2026-10-16 | table、pull-burst | 旧 6（10 チャンク） | なし | 20 | `my_c10.png`（手動で実行した分） |
| `compare_chunk_methods_delay5ms` | 2026-10-21 | table、pull-burst | 旧 6（10 チャンク） | 全リンク片道 5 ms | 20 | `compare_chunk_methods_delay5ms.png` |
| `compare_chunk_methods_delay10ms` | 2026-10-20 | table、pull-burst | 旧 6（10 チャンク） | 全リンク片道 10 ms | 20 | `compare_chunk_methods_delay10ms.png` |
| `compare_chunk_methods_step1` | 2026-10-03 | table、pull-sequential | 旧 4（4 チャンク） | なし | 10 | なし（chunk_pull の PIT をチャンクごとに分ける前の確認） |
| `compare_chunk_methods_step2` | 2026-10-03 | pull-sequential | 旧 4（4 チャンク） | なし | 10 | なし（分けた後の確認） |

10 チャンクの遅延なしは 3 回測っていて、どれも 0.4 ms 以内で同じ結果になっている。
リンクの遅延ありは、取得時間の開始を Consumer が記録した送信時刻にしている（`../README.md` の「取得時間の測り方」）。

### チャンク数の比較（横軸 = チャンク数）

1 セッションの中で `content1〜10.bin` を順に 10 回ずつ取得したもの。CSV に `content_id` と `n_chunks` の列がある。

| 名前 | 計測した日 | 方式 | コンテンツ | リンクの遅延 | セッション | グラフ |
|---|---|---|---|---|---|---|
| `chunk_sweep_pull` | 2026-10-21 | pull-burst | `content1〜10.bin` | なし | 20 | `chunk_sweep_pull.png` |

グラフの s1 の点は、セッションごとに 4〜10 回目（s1 から返る 7 回）を平均し、それを 20 セッション分平均した値。

### パケットの流れの図

| グラフ | 内容 |
|---|---|
| `timeline_s2.png` | 10 チャンクを s2 から返す回（3 回目）の、各パケットがノードを通った時刻（table と pull） |
| `timeline_s1.png` | 同じく s1 から返す回（5 回目） |

1 セッション分の BMv2 の pcap から `../plot_timeline.py` で描いたもの。元の pcap は残していない。

## 前の段階の結果（今の比較には使わない）

| ファイル | 内容 | 注意 |
|---|---|---|
| `csv/compare_icn_ip.csv`、`png/compare_icn_ip.png` | pit_table（ICN）と ip_baseline（IP）、1 チャンク（`image1.png` など）。`../run_compare_graph.py` | 手法は [../METHODOLOGY.md](../METHODOLOGY.md) |
| `csv/compare_icn_ip_memcache.csv`、`png/compare_icn_ip_memcache.png` | 上と同じ比較の別の計測（2026-06-29） | 何を変えたかの記録がない。名前からは、Producer がコンテンツを起動時にメモリに読み込んでおく版と考えられる |
| `log/run_compare_52s*.log` | 上の比較（52 セッション）の実行ログ | |
| `csv/compare_chunk_ip.csv`、`png/compare_chunk_ip.png` | chunk_table と ip_baseline、`image4.png`（4 チャンク）。`../run_compare_chunk_graph.py` | 前の Consumer で測っている。6 セッションのみで、ばらつきが大きい（VirtualBox 環境） |
| `csv/compare_chunk_ip_means.csv` | 上の平均 | 作ったスクリプトと手順が分からない |
| `csv/chunk_pull_10sessions.csv`、`csv/ip_chunk_10sessions.csv` | chunk_pull と IP、4 チャンク、10 セッション（2026-08-19） | 前の Consumer で測っている。chunk_pull は約 2.7 秒（tcpdump の書き込み待ちが入っている） |
| `csv/compare_chunk_table_pull.csv`、`png/compare_chunk_table_pull.png` | chunk_table と chunk_pull | 数値をコードに直接書いて描いている。chunk_pull は前の Consumer の問題で約 2.7 秒になっている |

## グラフの作り直し方

`p4-icn-router/` から実行する（matplotlib と日本語フォントが必要。`python3 -m pip install matplotlib matplotlib-fontja`）。

```bash
# 方式の比較（4 チャンクと 10 チャンクを並べる）
python3 plot_compare_chunk_methods.py \
    --panel "4 チャンク（1 KB）:results/csv/compare_chunk_methods_raw.csv" \
    --panel "10 チャンク（2.5 KB）:results/csv/compare_chunk_methods_c10_raw.csv" \
    --out results/png/compare_chunk_methods.png

# 方式の比較（1 枚ずつ）
python3 plot_compare_chunk_methods.py \
    --panel "遅延なし（10 チャンク）:results/csv/compare_chunk_methods_c10_run2_raw.csv" \
    --out results/png/compare_chunk_methods_c10_run2.png
python3 plot_compare_chunk_methods.py \
    --panel "10 チャンク（2.5 KB）:results/csv/my_c10_raw.csv" --out results/png/my_c10.png
for d in 5 10; do
  python3 plot_compare_chunk_methods.py \
      --panel "全リンク片道 $d ms（10 チャンク）:results/csv/compare_chunk_methods_delay${d}ms_raw.csv" \
      --out results/png/compare_chunk_methods_delay${d}ms.png
done

# チャンク数の比較
python3 plot_chunk_sweep.py results/csv/chunk_sweep_pull_raw.csv \
    --systems pull-burst --out results/png/chunk_sweep_pull.png
```

グラフは平均の線だけを描く（標準偏差は `*_summary.csv` の `std_ms` にある）。
