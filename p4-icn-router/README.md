# p4-icn-router

P4（BMv2）で ICN ルータ（IWP）を実装し、キャッシュ配置の工夫を評価する研究のリポジトリ。

- **目的**: キャッシュ配置を工夫した ICN を普及させる
- **アプローチ**: IWP をプログラム可能なスイッチ（P4）の上に実装する。理由は [P4を使う理由.txt](P4を使う理由.txt)
- **今できていること**: コンテンツ ID + MCD による on-path キャッシュ（要求のたびにキャッシュが
  Consumer 側へ 1 台ずつ移る）と、複数パケット（チャンク）に分けた大きいコンテンツの転送

## ディレクトリ

| ディレクトリ | 内容 | 状態 |
|---|---|---|
| [`chunk_table/`](chunk_table/README.md) | 複数チャンク + MCD。Interest 1 本で、キャッシュを持つスイッチが全チャンクを返す（clone + recirculate） | **採用。今後の土台** |
| [`chunk_pull/`](chunk_pull/README.md) | 複数チャンク + MCD。チャンクごとに Interest を送る | 比較用 |
| `pit_table/` | PIT + MCD キャッシュ。1 コンテンツ = 1 Data（256 B） | 完了（前の段階） |
| `mcd_cache/` | MCD キャッシュの実装（今の研究の流れとは別の目的で作成） | 完了 |
| `ip_baseline/` | 比較用の IPv4 転送 + UDP 要求／応答（キャッシュなし） | 完了 |
| `contents/` | Producer が返すコンテンツの元ファイル（下を参照） | - |
| [`results/`](results/README.md) | 計測結果（`csv/`、`png/`、`log/`） | - |

chunk_table を採用した理由は [chunk_tableを採用する理由.txt](chunk_tableを採用する理由.txt)。

### コンテンツ（`contents/`）

| ファイル | 使うプロジェクト | 内容 |
|---|---|---|
| `content1.bin` 〜 `content10.bin` | chunk_table、chunk_pull | `contentN.bin` = N チャンク（256 B × N）の乱数。content_id N で返す。`make_contents.py` で作る（`random.Random(N)` を使うので、何度作っても同じ中身） |
| `image1.png` 〜 `image4.png` | pit_table、mcd_cache、ip_baseline | 動作確認用の画像（`image4.png` だけ 1024 B = 4 チャンク） |

受け取ったコンテンツは、各プロジェクトの `received_image/` に保存する。

## 共通の環境

### トポロジ

```
h1（Consumer）─ s1 ─ s2 ─ s3 ─ h2（Producer）
```

- どのプロジェクトも同じ。スイッチは BMv2（simple_switch_grpc）、ホストとリンクは Mininet
- ポート: s1 は 1 = h1 側、2 = s2 側。s2 は 1 = s1 側、2 = s3 側。s3 は 2 = s2 側、1 = h2 側

### MCD（Move Copy Down）

- Producer（または、キャッシュから返したスイッチ）は Data を `flag = 1` で送る
- `flag == 1` の Data を受け取ったスイッチは、それをキャッシュし、`flag = 0` にして下流へ流す。
  そのため、1 回の取得でキャッシュされるのは、返した場所の 1 つ下流のスイッチだけ
- エッジ（Consumer の隣、s1）以外のスイッチがキャッシュから返したら、そのキャッシュを消す
- 結果として、同じコンテンツを続けて要求すると、返す場所が 1 台ずつ Consumer に近づく

| 要求 | 1 回目 | 2 回目 | 3 回目 | 4 回目以降 |
|---|---|---|---|---|
| 返す場所 | h2（Producer） | s3 | s2 | s1 |

### 実行環境

p4c、BMv2（`simple_switch_grpc`）、Mininet が入った Linux で実行する。
p4lang/tutorials の VM（VirtualBox など。`../vm-ubuntu-24.04/`）でも、Docker のコンテナ（[../DOCKER.md](../DOCKER.md)）でもよい。
このリポジトリの構成（`p4-icn-router/` の 1 つ上に `utils/` がある）のまま使う。

- コマンドはすべて `p4-icn-router/` から実行する（各方式のフォルダで実行するものは、そう書いている）
- Mininet を使うスクリプト（`run_compare_chunk_methods.py`、`chunk_table/run_chunk_experiment.py`、`make run`）は
  root 権限が必要。root でなければ、`make run` と同じように `sudo PATH=$PATH` を前に付ける
  （p4c や Python のパッケージを、今の PATH にあるものを使うため）

  ```bash
  sudo PATH=$PATH python3 run_compare_chunk_methods.py -s 1 --content-id 4
  ```

- グラフを作るスクリプトは matplotlib と日本語フォントが必要。入っていなければ
  `python3 -m pip install matplotlib matplotlib-fontja` で入れる
- tcpdump を使う（`consumer_bench.py` が h1 で記録する）

取得時間は、動かすマシンや環境（VM かどうかなど）で変わる。比べる計測は同じ環境で行う。

## スクリプト

### 今の計測で使うもの

| スクリプト | 何をするか |
|---|---|
| `consumer_bench.py` | h1 で動かす共通の Consumer。`--mode table`（Interest 1 本）と `--mode pull`（chunk 0 の Interest を送り、届いたら残りのチャンクの Interest をまとめて送る）。同じコンテンツを連続で N 回取得し、取得時間・返した場所・内容が正しいかを `RESULT,...` の行で出力する |
| `run_compare_chunk_methods.py` | 実験の本体。Mininet を起動して Producer と Consumer を動かし、方式を交互に何セッションも計測して CSV に保存する。チャンク数の比較（複数のコンテンツ）とリンクの遅延にも対応 |
| `plot_compare_chunk_methods.py` | 上の CSV から、横軸を要求回数（= 返す場所）にした方式の比較グラフを作る |
| `plot_chunk_sweep.py` | 上の CSV（複数のコンテンツ）から、横軸をチャンク数にしたグラフを作る |
| `plot_timeline.py` | 1 回の取得の中で、各パケットがいつどのノードを通ったかを図にする（BMv2 の pcap を読む） |
| `contents/make_contents.py` | `content1〜10.bin` を作る |

### 前の段階のもの（今の比較には使わない）

| スクリプト | 何をするか | 使わない理由 |
|---|---|---|
| `run_compare_graph.py` | pit_table（ICN）と ip_baseline（IP）を計測してグラフにする（1 チャンク） | 前の段階の比較。手法は [METHODOLOGY.md](METHODOLOGY.md) |
| `run_compare_chunk_graph.py`、`plot_compare_chunk_ip.py` | chunk_table と ip_baseline を `image4.png`（4 チャンク）で比べる | 前の Consumer で測っている。6 セッションのみ。IP との比較は今の方法で測り直す予定 |
| `run_compare_chunk_table_pull_graph.py` | chunk_table と chunk_pull のグラフ | 数値をコードに直接書いている。chunk_pull の値は前の Consumer の問題で約 2.7 秒になっていた |
| `chunk_table/benchmark_icn.py`、`chunk_pull/benchmark_icn.py` | 前の Consumer | chunk_pull 側は tcpdump の書き込みを待ってから次の Interest を送るため、チャンクごとに最大約 1 秒待たされていた |

## 実験の方法

### 計測の流れ（`run_compare_chunk_methods.py`）

```
1 セッション（方式ごと）
  Mininet 起動 → スイッチに表を書き込む → h2 で Producer（send_content.py）を起動
  → h1 で consumer_bench.py を動かし、同じコンテンツを 10 回続けて取得（0.2 秒おき）
     （コンテンツが複数なら、コンテンツごとに 10 回ずつ）
  → Mininet 停止
× セッション数（方式を交互に。セッションごとに、先に回す方式とコンテンツの順番を逆にする）
```

- 毎セッション Mininet を起動し直すので、1 回目はどのスイッチにもキャッシュがない状態から始まる
- 1 セッションの 10 回で、返す場所が h2 → s3 → s2 → s1 × 7 と移る
- 各試行で自動的に確認すること: 全チャンクが届いたか、返した場所（Data の `source_switch`）が
  上の表のとおりか、受け取った内容が元のファイルと一致するか

### 取得時間の測り方（`consumer_bench.py`）

- 両方式で同じ Consumer を使い、違いは Interest の送り方だけにしている
- Data は raw ソケット（AF_PACKET）で直接受け取り、Interest は組み立て済みのバイト列を送る
  （チャンクの間に Python の処理が入らないようにするため）
- h1 で tcpdump（`--immediate-mode`）を回し、試行がすべて終わった後に計算する
- 取得時間 = 開始 → 全チャンクがそろった時刻（最後に届いた未受信チャンクの Data の pcap 時刻）
  - 開始（遅延なし）: その試行の最初の Interest が h1 から出た pcap 時刻
  - 開始（`--link-delay` あり）: Consumer が最初の Interest を送る直前に記録した時刻。
    tcpdump は送信パケットを netem の遅延をかけた後に記録するので、pcap の時刻は遅延の分だけ遅れるため

### 実験 1: 方式の比較（返す場所ごと）

```bash
python3 run_compare_chunk_methods.py -s 20 --content-id 10 \
    --systems table,pull --out-prefix results/csv/compare_chunk_methods_c10

python3 -m pip install matplotlib matplotlib-fontja
python3 plot_compare_chunk_methods.py \
    --panel "10 チャンク（2.5 KB）:results/csv/compare_chunk_methods_c10_raw.csv" \
    --out results/png/compare_chunk_methods_c10.png
```

`--panel` を複数指定すると、パネルを横に並べる（例: 4 チャンクと 10 チャンク）。

### 実験 2: チャンク数を変える

1 セッションの中で、`content1〜10.bin` を順に 10 回ずつ取得する。

```bash
python3 run_compare_chunk_methods.py -s 20 --content-id 1,2,3,4,5,6,7,8,9,10 \
    --systems table --link-delay 5ms --out-prefix results/csv/chunk_sweep_table_delay5ms

python3 plot_chunk_sweep.py results/csv/chunk_sweep_table_delay5ms_raw.csv --systems table \
    --title "chunk_table（全リンク片道 5 ms）" --out results/png/chunk_sweep_table_delay5ms.png
```

遅延なしで測るときは `--link-delay` を外す。chunk_pull を測るときは `--systems pull` にする
（`chunk_sweep_pull` は、chunk_pull を遅延なしで測った結果）。

### 実験 3: リンクに遅延を付ける

全リンクに片道 d の遅延（Mininet の TCLink = tc netem）を付ける。各方式の `topology.json` は書き換えず、
遅延を書き足したものを作業フォルダに作って使う。

```bash
python3 run_compare_chunk_methods.py -s 20 --content-id 10 --systems table,pull \
    --link-delay 10ms --out-prefix results/csv/compare_chunk_methods_delay10ms
```

結果の CSV の `send_offset_ms`（pcap の Interest の時刻 − 記録した送信時刻）が約 d になっていれば、
遅延が正しくかかっている。

### 実験 4: パケットの流れの図

`--work-dir` に残った h1 と各スイッチの pcap から描く。`--work-dir` は絶対パスで指定する
（Mininet を起動する前に各方式のフォルダへ移動するため）。

```bash
python3 run_compare_chunk_methods.py -s 1 --content-id 10 --systems table,pull \
    --work-dir /tmp/timeline --out-prefix /tmp/timeline/res
python3 plot_timeline.py /tmp/timeline --session 1 --trial 3 --out results/png/timeline_s2.png
# --trial 3 = s2 から返す回、5 = s1 から返す回
```

### `run_compare_chunk_methods.py` のオプション

| オプション | 既定 | 内容 |
|---|---|---|
| `-s`, `--sessions` | 10 | セッション数 |
| `-n`, `--trials` | 10 | 1 セッションで同じコンテンツを取得する回数 |
| `-i`, `--interval` | 0.2 | 取得の間隔（秒） |
| `--content-id` | 4 | コンテンツ ID（N = `contentN.bin`）。カンマ区切りで複数指定できる |
| `--systems` | `table,pull` | `table`、`pull` をカンマ区切りで |
| `--link-delay` | なし | 全リンクの片道の遅延（例: `10ms`） |
| `--work-dir` | `/tmp/compare_chunk_methods` | BMv2 のログ、pcap、Consumer の出力を置く場所（絶対パス） |
| `--out-prefix` | `results/csv/compare_chunk_methods` | 結果の CSV（`<prefix>_raw.csv`、`<prefix>_summary.csv`） |
| `--producer-wait` | 2.5 | Producer を起動してから Consumer を動かすまでの待ち時間（秒） |
| `--skip-build` | - | P4 のコンパイルを省く |

### 結果の CSV（`*_raw.csv`）の列

| 列 | 内容 |
|---|---|
| `system`、`session`、`trial` | 方式、セッション番号、何回目の取得か |
| `content_id`、`n_chunks` | コンテンツ ID、チャンク数 |
| `link_delay`、`start_time` | リンクの遅延、取得時間の開始の取り方（`pcap` / `script`） |
| `latency_ms` | 取得時間 |
| `latency_pcap_ms`、`send_offset_ms` | pcap の時刻だけで計算した取得時間、pcap の Interest の時刻 − 記録した送信時刻（確認用） |
| `status` | `ok` / `timeout` |
| `interests`、`chunks` | 送った Interest の数、受け取ったチャンクの数 |
| `sources`、`expected_source` | 各チャンクを返した場所、MCD から想定される場所 |
| `max_gap_ms` | pull で、Data が届いてから次の Interest を送るまでの最大の間隔 |
| `verified` | 受け取った内容が元のファイルと一致したか |

古い結果の CSV には、後から追加した列（`content_id` など）がない。また、`system` の `pull` を `pull-burst` と書いている
（1 つずつ Interest を送る `pull-sequential` もあったが、使わないので削除した）。グラフのスクリプトは、どちらの名前でも読める。

## 主な結果

取得時間 ms、各 20 セッションの平均（s1 は 4〜10 回目の平均）。結果の一覧は [results/README.md](results/README.md)。

| 返す場所 | 4 チャンク table / pull | 10 チャンク table / pull | 10 チャンク、片道 5 ms | 10 チャンク、片道 10 ms |
|---|---|---|---|---|
| h2 | **5.01** / 8.22 | **7.16** / 13.11 | **46.86** / 90.31 | **86.89** / 170.26 |
| s3 | **5.37** / 7.27 | **9.25** / 11.34 | **38.99** / 70.77 | **69.05** / 130.95 |
| s2 | **4.42** / 5.09 | **8.16** / 8.99 | **28.18** / 48.62 | **48.08** / 88.79 |
| s1 | 2.86 / **2.67** | 6.58 / **5.79** | **16.59** / 25.98 | **26.63** / 46.01 |

- 遅延なしでは、Consumer の隣（s1）から返すときだけ chunk_pull が速い。
  chunk_pull は chunk 0 の往復を待つが、s1 から返すときは往復がほぼ 0 になり、
  chunk_table の「1 チャンクごとにスイッチの中を一周させる分」の方が大きくなるため
- リンクに遅延を付けると、すべての場所で chunk_table が速い。chunk_pull は往復が 1 回多いため
- チャンク数を変えた計測では、取得時間はチャンク数にほぼ比例する。
  chunk_table（全リンク片道 5 ms）は 1 チャンク増えるごとに、スイッチから返すとき約 0.6 ms、
  h2 から返すとき約 0.3 ms 増える（`results/png/chunk_sweep_table_delay5ms.png`）。
  chunk_pull（遅延なし）は 1 → 2 チャンクで chunk 0 の往復の分だけ大きく増え、その後はほぼ比例する
  （`results/png/chunk_sweep_pull.png`）

## ドキュメント

| ファイル | 内容 |
|---|---|
| [ROADMAP.md](ROADMAP.md) | 研究全体の計画 |
| [FIB・2次元トポロジ実験の予定.txt](FIB・2次元トポロジ実験の予定.txt) | 12 月までの予定（水平キャッシュの設計、名前、FIB、2 次元トポロジ） |
| [chunk_tableを採用する理由.txt](chunk_tableを採用する理由.txt) | chunk_table と chunk_pull の比較と、chunk_table を選んだ理由 |
| [水平キャッシュの設計.md](水平キャッシュの設計.md) | 水平キャッシュ（ECST、通知、リダイレクト）の設計 |
| [P4を使う理由.txt](P4を使う理由.txt) | P4 を使う理由、VPP・NFD・hICN との違い |
| [設計メモ.txt](設計メモ.txt) | IP 上で動く ICN の設計（FIB / LCST / ECST / PIT / NMT / NRS） |
| [METHODOLOGY.md](METHODOLOGY.md) | 前の段階の比較実験（pit_table と IP）の手法 |
| [chunk_table/CHUNK_CACHE_DESIGN.md](chunk_table/CHUNK_CACHE_DESIGN.md) | chunk_table のスイッチの詳しい設計 |
| [chunk_table/RESEARCH_POSITIONING.txt](chunk_table/RESEARCH_POSITIONING.txt) | 先行研究（port 511 版）との関係 |

## 今後の予定

詳細は [ROADMAP.md](ROADMAP.md) と [FIB・2次元トポロジ実験の予定.txt](FIB・2次元トポロジ実験の予定.txt)。

1. 水平キャッシュ（off-path キャッシング）のヘッダと実装の設計
2. コンテンツ名（ホストが各階層をハッシュにして固定長のフィールドに載せる）
3. FIB（名前の最長プレフィックス一致 → 出力ポート）。今の Interest の転送は送信元 MAC アドレスで経路を決め打ちしている
4. 2 次元トポロジでの実験
5. IP 上での動作（途中に通常の IP ルータがあっても通信できる）
