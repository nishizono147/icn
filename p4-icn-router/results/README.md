# 計測結果の一覧

| フォルダ | 中身 |
|---|---|
| `csv/` | 計測の生データ（`*_raw.csv`）と集計（`*_summary.csv`） |
| `png/` | グラフ |
| `log/` | 実行ログ |

同じ計測の CSV とグラフは、フォルダが違っても同じ名前で始まる
（例: `csv/compare_chunk_methods_c10_run2_raw.csv` と `png/compare_chunk_methods_c10_run2.png`）。
下の表のファイル名は、フォルダを省いて書いている。

chunk_table と chunk_pull の `content_id` の割り当ては 2026-10-21 に変えた。

| 期間 | content_id の割り当て |
|---|---|
| 2026-10-21 より前 | `4` = `image4.png`（4 チャンク）、`6` = `content10.bin`（10 チャンク） |
| 2026-10-21 から | `N` = `contentN.bin`（N チャンク、N = 1〜10） |

`content10.bin` は割り当てを変える前後で同じファイル（`random.Random(10)` で作った 2560 B）。
2026-10-21 より前の結果の CSV には content_id の列がないので、どのコンテンツで測ったかは下の表で確認する。

## run_compare_chunk_methods.py の結果（chunk_table と chunk_pull を同じ Consumer で交互に計測）

| ファイル | 計測した日 | コンテンツ | チャンク数 | リンクの遅延 | セッション |
|---|---|---|---|---|---|
| `compare_chunk_methods_step1_*` | 2026-10-03 | 旧 4（`image4.png`） | 4 | なし | 10 |
| `compare_chunk_methods_step2_*` | 2026-10-03 | 旧 4（`image4.png`） | 4 | なし | 10 |
| `compare_chunk_methods_raw.csv`、`_summary.csv` | 2026-10-03 | 旧 4（`image4.png`） | 4 | なし | 20 |
| `compare_chunk_methods_c10_*` | 2026-10-08 | 旧 6（`content10.bin`） | 10 | なし | 20 |
| `compare_chunk_methods_c10_run2_*` | 2026-10-09 | 旧 6（`content10.bin`） | 10 | なし | 20 |
| `my_c10_*` | 2026-10-16 | 旧 6（`content10.bin`） | 10 | なし | 20 |
| `compare_chunk_methods_delay10ms_*` | 2026-10-20 | 旧 6（`content10.bin`） | 10 | 全リンク片道 10 ms | 20 |
| `compare_chunk_methods_delay5ms_*` | 2026-10-21 | 旧 6（`content10.bin`） | 10 | 全リンク片道 5 ms | 20 |

## チャンク数を変えた計測（`--content-id 1,2,...,10`、CSV に content_id と n_chunks の列がある）

| ファイル | 計測した日 | 方式 | コンテンツ | リンクの遅延 | セッション |
|---|---|---|---|---|---|
| `chunk_sweep_pull_*` | 2026-10-21 | chunk_pull（pull-burst） | `content1〜10.bin` | なし | 20 |

## それより前のスクリプトの結果

`compare_chunk_ip*`、`compare_chunk_table_pull*`、`chunk_pull_10sessions.csv`、`ip_chunk_10sessions.csv` は、
前の Consumer（`benchmark_icn.py` など）で `image4.png`（4 チャンク）を測った結果。
`compare_icn_ip*` は pit_table と ip_baseline で `image1.png` などを測った結果。
