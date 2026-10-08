# chunk_pull — チャンクごとに Interest を送る方式

`chunk_table`（Interest 1 本でスイッチが全チャンクを返す）とは別に、
チャンクごとに Interest を送る方式を実装したディレクトリ。今後の実装の土台にする。

## 方式

1. Consumer が `Interest(content_id, chunk_id=0)` を送る
2. 返ってきた Data の `total_chunks` で総チャンク数 N を知る
3. `Interest(chunk_id=1..N-1)` を送る（1 Interest に 1 Data）
   - まとめて送る（burst）: chunk 0 が届いたら残りを一度に送る。計測ではこちらを使う
   - 1 つずつ送る（sequential）: 前のチャンクが届いてから次を送る
4. Consumer 側でチャンクをつなげて元のコンテンツに戻す

スイッチは `clone` / `recirculate` を使わない。キャッシュから返すときも、要求されたチャンクを 1 つだけ返す。

## スイッチ（`switch.p4`）

- **キャッシュ**: `content_cache[content_id * 10 + chunk_id]`（1 コンテンツ最大 10 チャンク）
- **PIT**: チャンクごと（`pit_table[content_id * 10 + chunk_id]` に戻りのポート）。
  Data が通ったらそのチャンクの分だけ消す。
  以前は content_id ごとに 1 つで Data が通るたびに消していたため、Interest をまとめて送ると
  最初の Data で PIT が消え、残りの Data が捨てられていた
- **MCD**: Data の `flag == 1` のときだけキャッシュし、`flag = 0` にして下流へ流す。
  エッジ（Consumer からの Interest、`icn.flag == 1`）以外でキャッシュから返したら、そのチャンクを消す
- **Interest の転送**: `foward_interest` 表（キーは送信元 MAC アドレス）

### 制約

- PIT の 1 つの欄に記録できるポートは 1 つだけ。Consumer が 1 台である前提
  （複数の Consumer から同じチャンクの要求が同時に来ると、後から来た方で上書きされる）
- PIT の記録に期限はない
- キャッシュの置き換えはない

## ヘッダ

| | フィールド |
|---|---|
| Interest（EtherType `0x88B5`） | `content_id`(32) `type`(16) `flag`(8) `source_switch`(8) **`chunk_id`(16)** |
| Data（EtherType `0x88B6`） | `content_id`(32) `total_chunks`(16) `chunk_id`(16) `flag`(8) `source_switch`(8) `data`(256 B) |

Interest に `chunk_id` がある点だけが chunk_table と違う。Data は同じ。

## 使い方

計測は 1 つ上のディレクトリの `run_compare_chunk_methods.py` で行う（`../README.md` を参照）。

手で動かす場合（Docker のコンテナ内）:

```bash
cd /work/p4-icn-router/chunk_pull
make run

mininet> h2 python3 send_content.py --quiet &
mininet> h1 python3 ../consumer_bench.py 4 --mode pull --pull-strategy burst -n 10
mininet> h1 python3 fetch_content.py 4      # 1 回取得して画像を保存（動作確認用）
```

コンテンツのファイルは `../chunk_table/` のものを使う
（`content_id` 4 = `image4.png`、4 チャンク / 6 = `content10.bin`、10 チャンク）。

## ファイル

| ファイル | 内容 |
|---|---|
| `switch.p4` | PIT（チャンクごと）+ MCD キャッシュ。要求されたチャンクを 1 つ返す |
| `send_content.py` | Producer。Interest 1 つに Data を 1 つ返す（組み立て済みのフレームを raw ソケットで送る） |
| `fetch_content.py` | 1 回取得して画像を保存する Consumer（動作確認用。1 つずつ送り、録画ファイルで到着を待つので遅い） |
| `benchmark_icn.py` | 前の計測スクリプト（使わない。取得時間に tcpdump のバッファ待ちが入る） |
| `*-runtime.json` | スイッチ ID と Interest の転送先 |
