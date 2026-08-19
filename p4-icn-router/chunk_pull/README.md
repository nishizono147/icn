# chunk_pull — Method A (Per-Chunk Interest Pull)

`chunk_table`（Interest 1 本 + clone/recirculate）とは別に、**方法A** を実装したディレクトリです。

## 方式

1. Consumer が `Interest(content_id, chunk_id=0)` を 1 本送信
2. 返ってきた Data の `total_chunks` で総 chunk 数 N を学習
3. `Interest(chunk_id=1..N-1)` を順に送信（各 1 Data 応答）
4. Consumer 側で chunk を再構成

**clone / recirculate は使いません。** キャッシュヒット時も要求された chunk 1 本だけ返します。

## プロトocol 差分（chunk_table との比較）

| 項目 | chunk_table | chunk_pull |
|------|-------------|------------|
| Interest | content_id のみ | **+ chunk_id** |
| 1 要求あたり Interest | 1 本 | **N 本** |
| スイッチ | clone + recirculate | **単一 Data 返却** |
| Consumer | 受動受信 | **能動 pull** |

## 使い方

```bash
cd p4-icn-router/chunk_pull
make build && make run

# Mininet CLI:
# h2 (Producer):
python3 send_content.py --quiet

# h1 — 1 回取得 + 画像保存:
python3 fetch_content.py 4

# h1 — ベンチマーク (image4 = 4 chunks):
python3 benchmark_icn.py 4 -n 10 -i 0.2
```

コンテンツファイルは `../chunk_table/image*.png` を参照します（image4 = 1024 B = 4×256 B）。

## ファイル

| ファイル | 役割 |
|----------|------|
| `switch.p4` | PIT + MCD キャッシュ、chunk_id 指定で 1 Data 返却 |
| `fetch_content.py` | Method A Consumer |
| `send_content.py` | chunk_id ごとに 1 Data を返す Producer |
| `benchmark_icn.py` | 取得時間計測（first Interest → last Data） |
