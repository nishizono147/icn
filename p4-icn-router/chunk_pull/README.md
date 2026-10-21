# chunk_pull — チャンクごとに Interest を送る方式（比較用）

1 つのコンテンツを 256 B ずつのチャンクに分けて運ぶ。Consumer はチャンクごとに Interest を送り、
スイッチ（または Producer）は Interest 1 本に Data を 1 個返す。
[chunk_table](../chunk_table/README.md)（Interest 1 本で全チャンクを返す）と比べるために作った。
今後の土台は chunk_table にした（理由は [../chunk_tableを採用する理由.txt](../chunk_tableを採用する理由.txt)）。

## 方式

```
Consumer（h1）                         キャッシュを持つスイッチ / Producer（h2）
   │ Interest(chunk 0) ─────────────────────▶│
   │◀──────────────────── Data chunk 0       │  total_chunks で全チャンク数 N を知る
   │ Interest(chunk 1) ─────────────────────▶│
   │ Interest(chunk 2) ─────────────────────▶│  burst: 残りをまとめて送る
   │ …                                       │
   │◀──────────────────── Data chunk 1       │
   │◀──────────────────── Data chunk 2 …     │
```

1. Consumer が `Interest(content_id, chunk_id = 0)` を送る
2. 返ってきた Data の `total_chunks` で全チャンク数 N を知る
3. `Interest(chunk_id = 1 〜 N-1)` を送る
   - **burst**（まとめて送る）: chunk 0 が届いたら残りを一度に送る。計測ではこちらを使う
   - **sequential**（1 つずつ送る）: 前のチャンクが届いてから次を送る
4. Consumer 側でチャンクをつなげて元のコンテンツに戻す

chunk_table と比べると、chunk 0 が届いて残りの Interest が戻ってくるまでの往復が 1 回多い。
その代わり、スイッチは clone も recirculate も使わず、Data を 1 個ずつ返すだけでよい。

## スイッチ（`switch.p4`）

### データ構造

**register**

| 名前 | 大きさ | インデックス | 中身 |
|---|---|---|---|
| `content_cache` | `bit<2048>` × 10240 | `content_id * 10 + chunk_id` | キャッシュしたチャンクの中身（256 B） |
| `pit_table` | `bit<9>` × 10240 | `content_id * 10 + chunk_id` | PIT。チャンクごとに、Interest が来たポート |
| `total_chunks_reg` | `bit<16>` × 1024 | `content_id` | そのコンテンツのチャンク数 |
| `switch_id_reg` | `bit<8>` × 1 | 0 | 自分のスイッチ番号（1〜3） |

PIT をチャンクごとにしているのは、Interest をまとめて送るため。以前はコンテンツごとに 1 つで、
Data が通るたびに消していたので、最初の Data で PIT が消え、残りの Data が捨てられていた。

**表**（コントローラが `s*-runtime.json` から書き込む。chunk_table と同じ）

| 名前 | キー | アクション |
|---|---|---|
| `switch_config` | `etherType`（Interest と Data の 2 つ） | `set_local_switch_id(switch_id)` |
| `foward_interest` | 送信元 MAC アドレス | `dup_interest(dstAddr, port)`: Interest を次のスイッチ（または h2）へ送る |

clone session と、clone・recirculate のための metadata はない。

### Interest を受け取ったとき

`content_cache[content_id * 10 + chunk_id]` を見る。

- **キャッシュにあるなら**: PIT に来たポートを書き、パケットをそのチャンクの Data に作り替えて返す。
  自分がエッジでなければ（Interest の `flag != 1`）、そのチャンクのキャッシュを消す
- **キャッシュにないなら**: PIT に来たポートを書き、`flag = 0` にして `foward_interest` で次へ送る

### Data を受け取ったとき

1. `flag == 1` なら、`content_cache` と `total_chunks_reg` に書き、`flag = 0` にする（MCD）
2. `pit_table[content_id * 10 + chunk_id]` のポートへ送り、その PIT を消す

## ヘッダ

| | EtherType | フィールド |
|---|---|---|
| Interest | `0x88B5` | `content_id`(32) `type`(16) `flag`(8) `source_switch`(8) **`chunk_id`(16)** |
| Data | `0x88B6` | `content_id`(32) `total_chunks`(16) `chunk_id`(16) `flag`(8) `source_switch`(8) `data`(256 B) |

Interest に `chunk_id`（要求するチャンクの番号）がある点だけが chunk_table と違う。Data は同じ。

## 制約

- 1 コンテンツ最大 10 チャンク、content_id は 0〜1023（chunk_table と同じ）
- PIT の 1 つの欄に記録できるポートは 1 つだけ。Consumer が 1 台である前提
  （複数の Consumer から同じチャンクの要求が同時に来ると、後から来た方で上書きされる）。期限もない
- キャッシュの置き換えはない
- Interest の転送は送信元 MAC アドレスで経路を決め打ちしている
- 1 つのコンテンツにつき Interest が N 本流れる。途中のスイッチは、チャンクごとに Interest と Data の両方を処理する

## 使い方

### 計測（1 つ上のディレクトリで）

```bash
cd /work/p4-icn-router
python3 run_compare_chunk_methods.py -s 20 --content-id 10 --systems pull-burst \
    --out-prefix results/csv/<名前>
```

`--systems pull-sequential` で 1 つずつ送る方式も測れる。チャンク数・リンク遅延の実験とオプションは
[../README.md](../README.md) を参照。

### 手で動かす（Docker のコンテナ内）

```bash
cd /work/p4-icn-router/chunk_pull
make run                 # P4 をコンパイル → Mininet 起動 → 表を書き込む

mininet> h2 python3 send_content.py --quiet &                                  # Producer
mininet> h1 python3 ../consumer_bench.py 4 --mode pull --pull-strategy burst -n 10
mininet> h1 python3 fetch_content.py 4      # 1 回取得して received_image/content4.bin に保存
mininet> h1 python3 send_interest.py 4 2    # content 4 の chunk 2 の Interest を 1 本だけ送る
mininet> exit

make stop                # Mininet の後片付け
make clean               # build/、logs/、pcaps/ を消す
```

`fetch_content.py` は動作確認用で、1 つずつ送り、tcpdump の記録で到着を待つので遅い。取得時間の計測には使わない。

## 計測で分かっていること

- 遅延なしでは、Consumer の隣（s1）から返すときだけ chunk_table より速い
  （10 チャンクで 5.79 ms と 6.58 ms）。それ以外の場所や、リンクに遅延を付けた場合は遅い
- チャンク数を 1〜10 に変えると、2 チャンク以上で取得時間はチャンク数にほぼ比例する。
  1 → 2 チャンクで大きく増えるのは、2 チャンク以上で chunk 0 の往復を待つため
  （[../results/png/chunk_sweep_pull.png](../results/png/chunk_sweep_pull.png)）

結果の一覧は [../results/README.md](../results/README.md)。

## ファイル

| ファイル | 内容 |
|---|---|
| `switch.p4` | スイッチのプログラム（上の仕組み） |
| `topology.json` | トポロジ（h1 ─ s1 ─ s2 ─ s3 ─ h2） |
| `s1-runtime.json`、`s2-`、`s3-` | スイッチ番号と Interest の転送先 |
| `Makefile` | `make run` / `make stop` / `make clean`（中身は `../../utils/Makefile`） |
| `send_content.py` | Producer。`../contents/contentN.bin` を content_id N として読み込み、Interest 1 本に、要求されたチャンクの Data を 1 個返す（組み立て済みのフレームを raw ソケットで送る） |
| `fetch_content.py` | 1 回取得して保存する Consumer（動作確認用） |
| `send_interest.py` | 指定したチャンクの Interest を 1 本送る（Scapy） |
| `icn_header.py`、`payload_header.py` | Interest と Data のヘッダの定義（Scapy） |
| `benchmark_icn.py` | 前の計測スクリプト（使わない。取得時間に tcpdump の書き込み待ちが入る） |
