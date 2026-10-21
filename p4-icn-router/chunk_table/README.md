# chunk_table — Interest 1 本で全チャンクを返す方式（採用）

1 つのコンテンツを 256 B ずつのチャンクに分けて運ぶ。Consumer は Interest を 1 本だけ送り、
キャッシュを持つスイッチ（または Producer）が全チャンクを続けて返す。
今後の実装（名前、FIB、水平キャッシュ）はこの方式を土台にする。
選んだ理由は [../chunk_tableを採用する理由.txt](../chunk_tableを採用する理由.txt)。

## 方式

```
Consumer（h1）                       キャッシュを持つスイッチ / Producer（h2）
   │ Interest(content_id) 1 本 ───────────▶│
   │◀─────────────── Data chunk 0          │
   │◀─────────────── Data chunk 1          │  スイッチは Interest のコピーを
   │◀─────────────── ...                   │  中で一周させながら 1 個ずつ作る
   │◀─────────────── Data chunk N-1        │
```

- Consumer は全部で何チャンクあるかを先に知らなくてよい（Data の `total_chunks` に書いてある）
- Producer（`send_content.py`）は Interest 1 本に、組み立て済みの N 個の Data を続けて送る
- スイッチがキャッシュから返すときは、clone と recirculate で Data を 1 個ずつ作る（下を参照）

## スイッチ（`switch.p4`）

### データ構造

**register**（パケットの処理中に読み書きできる）

| 名前 | 大きさ | インデックス | 中身 |
|---|---|---|---|
| `content_cache` | `bit<2048>` × 10240 | `content_id * 10 + chunk_id` | キャッシュしたチャンクの中身（256 B） |
| `total_chunks_reg` | `bit<16>` × 1024 | `content_id` | そのコンテンツのチャンク数（キャッシュを消すと 0） |
| `pit_table` | `bit<9>` × 1024 | `content_id` | PIT。Interest が来たポート（= Data を返すポート） |
| `switch_id_reg` | `bit<8>` × 1 | 0 | 自分のスイッチ番号（1〜3）。Data の `source_switch` に入れる |

**表**（コントローラが `s*-runtime.json` から書き込む）

| 名前 | キー | アクション |
|---|---|---|
| `switch_config` | `etherType`（Interest と Data の 2 つ） | `set_local_switch_id(switch_id)`: 自分の番号を `switch_id_reg` に書く |
| `foward_interest` | 送信元 MAC アドレス | `dup_interest(dstAddr, port)`: Interest を次のスイッチ（または h2）へ送る。宛先 MAC を書き換える |

**clone session**（`s*-runtime.json` の `clone_session_entries`）: 番号 100。コピーの出力先は Consumer 側のポート
（s1 と s2 は 1、s3 は 2）。

**metadata**（clone と recirculate の後も値を保つ。`@field_list(FL_SERVE)`）

| 名前 | 中身 |
|---|---|
| `serving_from_cache` | キャッシュから返している途中か |
| `serve_content_id`、`serve_total` | 返しているコンテンツと、そのチャンク数 |
| `current_chunk` | 次に作るチャンクの番号 |
| `clear_cache_after_serve` | 返し終わったらキャッシュを消すか（エッジ以外なら 1） |

### Interest を受け取ったとき

1. **recirculate で戻ってきたコピーなら**（`serving_from_cache == 1` かつ `current_chunk > 0`）:
   `current_chunk` 番のチャンクを返す（下の「キャッシュから返す流れ」）
2. **キャッシュにあるなら**（`content_cache[content_id * 10]`、つまり chunk 0 が 0 でない）:
   キャッシュから返し始める（`begin_cache_serve`）
3. **キャッシュにないなら**: `pit_table[content_id]` に来たポートを書き、`flag = 0` にして
   `foward_interest` で次へ送る

Consumer が送る Interest は `flag = 1`、スイッチが転送した Interest は `flag = 0`。
そのため `flag == 1` の Interest を受け取ったスイッチは、自分がエッジ（Consumer の隣）だと分かる。

### キャッシュから返す流れ（clone + recirculate）

```
Interest が届く
  └ ingress: PIT に来たポートを書く。チャンク数が 2 以上なら、Interest のコピーを作る（I2E clone）
             元のパケットを chunk 0 の Data に作り替えて、Consumer 側へ送る
       └ コピー: egress で recirculate → もう一度 ingress へ（current_chunk = 1）
            └ ingress: コピーを chunk 1 の Data に作り替えて送る。まだ残りがあれば、またコピーを作る
                 └ コピー: recirculate → chunk 2 → … → chunk N-1 で終わり
```

- 1 個の Data を作るたびに、Interest のコピーがスイッチの中を一周する。BMv2 では、この一周のため
  Data の間隔が約 0.5〜0.6 ms になる（chunk_pull でスイッチが Interest に応える間隔より約 0.05〜0.08 ms 長い）
- 最後のチャンクを作ったとき、`clear_cache_after_serve == 1`（エッジ以外）なら、そのコンテンツの
  キャッシュ（10 個分）と `total_chunks_reg` を 0 にする

### Data を受け取ったとき

1. `flag == 1` なら、`content_cache` と `total_chunks_reg` に書き、`flag = 0` にする（MCD）
2. `pit_table[content_id]` のポートへ送る。最後のチャンク（`chunk_id + 1 == total_chunks`）が通ったら PIT を消す

送り出す Data の MAC アドレスは、送信元・宛先とも `ff:ff:ff:ff:ff:ff` にしている。

## ヘッダ

| | EtherType | フィールド |
|---|---|---|
| Interest | `0x88B5` | `content_id`(32) `type`(16) `flag`(8) `source_switch`(8) |
| Data | `0x88B6` | `content_id`(32) `total_chunks`(16) `chunk_id`(16) `flag`(8) `source_switch`(8) `data`(256 B) |

- `type`: 上位のプロトコル（今は `0x11` を入れているだけで、スイッチは見ない）
- `flag`: Interest では「Consumer から直接来たか」、Data では「受け取ったスイッチがキャッシュするか」（MCD）
- `source_switch`: Data を作った場所（0 = Producer、1〜3 = s1〜s3）。計測で返した場所を確かめるのに使う

## 制約

- 1 コンテンツ最大 10 チャンク（キャッシュのインデックスが `content_id * 10 + chunk_id` のため）。
  11 チャンク以上の Data が来たときの確認はしていない
- content_id は 0〜1023（`pit_table`、`total_chunks_reg` の大きさ）
- キャッシュにあるかは chunk 0 だけで判断する（chunk 0 の中身が全部 0 だと、ないと判断される）
- PIT はコンテンツごとに 1 つで、記録できるポートも 1 つ。Consumer が 1 台である前提。期限もない
- キャッシュの置き換えはない
- Interest の転送は送信元 MAC アドレスで経路を決め打ちしている（FIB はまだない）
- clone と recirculate は BMv2 では動くが、実機のスイッチでは recirculate がチップの処理能力を使う。
  チャンク数が多いと、ほかのパケットの処理に使える分が減る
- 1 個目の Data は、同じ egress のスレッドでコピーの処理が終わるのを待ってから送られるので、
  chunk_pull より 0.2〜0.4 ms 遅い

## 使い方

### 計測（1 つ上のディレクトリで）

```bash
cd /work/p4-icn-router
python3 run_compare_chunk_methods.py -s 20 --content-id 10 --systems table \
    --out-prefix results/csv/<名前>
```

オプションや、チャンク数・リンク遅延の実験は [../README.md](../README.md) を参照。

### 手で動かす（Docker のコンテナ内）

```bash
cd /work/p4-icn-router/chunk_table
make run                 # P4 をコンパイル → Mininet 起動 → 表と clone session を書き込む

mininet> h2 python3 send_content.py --quiet &                  # Producer
mininet> h1 python3 ../consumer_bench.py 4 --mode table -n 10  # 10 回取得して取得時間を表示
mininet> exit

make stop                # Mininet の後片付け
make clean               # build/、logs/、pcaps/ を消す
```

取得したコンテンツをファイルに保存して確かめる場合:

```bash
mininet> h2 python3 send_content.py &
mininet> h1 python3 receive.py &         # 受信してチャンクをつなぎ、received_image/content4.bin に保存
mininet> h1 python3 send_interest.py 4   # Interest を 1 本送る
```

`make run` の間、各スイッチのログは `logs/s1.log` など、ポートごとの pcap は `pcaps/` に残る。

### 自動の動作確認

```bash
cd /work/p4-icn-router/chunk_table
python3 run_chunk_experiment.py
```

content 4（4 チャンク）を続けて取得し、次のことを確かめる。

- 1 回目: h2 から返り、全チャンクが届き、内容が元のファイルと一致する。キャッシュされるのは s3 だけ
- 2・3 回目: キャッシュが s2 → s1 へ移り、返したスイッチのキャッシュは消える
- 4 回目: s1 から返り、h2 に Interest が届かない。内容が元のファイルと一致する

## ファイル

| ファイル | 内容 |
|---|---|
| `switch.p4` | スイッチのプログラム（上の仕組み） |
| `topology.json` | トポロジ（h1 ─ s1 ─ s2 ─ s3 ─ h2） |
| `s1-runtime.json`、`s2-`、`s3-` | スイッチ番号、Interest の転送先、clone session |
| `Makefile` | `make run` / `make stop` / `make clean`（中身は `../../utils/Makefile`） |
| `send_content.py` | Producer。`../contents/contentN.bin` を content_id N として読み込み、Interest 1 本に N 個の Data を返す（組み立て済みのフレームを raw ソケットで送る） |
| `receive.py` | 手で確かめる用の Consumer。Data を受け取ってつなぎ、`received_image/` に保存する |
| `send_interest.py` | Interest を 1 本送る（Scapy） |
| `run_chunk_experiment.py` | 自動の動作確認 |
| `icn_header.py`、`payload_header.py` | Interest と Data のヘッダの定義（Scapy） |
| `benchmark_icn.py` | 前の計測スクリプト（使わない。今は `../consumer_bench.py`） |
| `CHUNK_CACHE_DESIGN.md` | スイッチの設計の詳しい説明（研究発表用） |
| `RESEARCH_POSITIONING.txt` | 先行研究（port 511 版）との関係 |
| `cache_migration_demo.gif`、`consumer_reassemble_demo.gif` | 説明用のアニメーション（`generate_*_demo.py` で作る。`image4.png` を使っていたときのもの） |
| `assets/topology.png` | トポロジの図 |
