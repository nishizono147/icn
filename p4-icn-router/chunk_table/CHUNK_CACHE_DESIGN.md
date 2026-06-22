# 複数チャンク対応 ICN ルータの設計説明

研究発表用ドキュメント。`chunk_table/switch.p4` が実装する
**チャンク分割コンテンツのキャッシュと、キャッシュヒット時の複数チャンク配信** の
ロジックを説明する。

---

## 1. 概要

### 1.1 解決する課題

従来の `pit_table` 実装では、1 コンテンツ = 1 Data パケット（最大 256 バイト）を前提としていた。
これでは 1 KB 以上の画像など大きなコンテンツをそのまま扱えない。

本実装（`chunk_table`）では次を実現する。

1. **Producer からの応答を複数チャンク（256 B 単位）に分割**して送受信する
2. **中継スイッチ**にチャンク単位でキャッシュする（`pit_table` と同様の **flag 制御による段階的配置**）
3. **Interest ごとにキャッシュが Consumer 側へ移動**し、最寄りスイッチが
   **複数 Data パケット** として返す（Producer へは行かない）

### 1.2 ネットワーク構成

```
h1 (Consumer) ─ s1 ─ s2 ─ s3 ─ h2 (Producer)
     10.0.1.1              10.0.2.2
```

- ホップ数: 3（Consumer から Producer まで）
- スイッチ: BMv2 + P4_16（v1model）
- 検証例: `image4.png`（1024 B → **4 チャンク**）

### 1.3 2 つのシナリオ（混同しやすい点）

| シナリオ | Interest の clone | Data の出どころ | キャッシュの位置 |
|----------|-------------------|-----------------|------------------|
| **初回（キャッシュミス）** | **なし** | h2 が 4 本の Data を別々に送信 | **s3 のみ**（Producer 側 1 台） |
| **2〜3 回目（段階的移動）** | **ヒットした 1 台だけ** | そのスイッチが register から 4 本生成 | s3→s2→s1 と **1 ホップずつ移動** |
| **4 回目以降（Warm）** | s1 のみ（内部） | s1 が register から 4 本生成 | **s1**（Consumer 直近） |

**Interest の clone は全スイッチで起きるわけではない。**
キャッシュヒットした 1 台の内部だけで、Consumer から来た Interest 1 本から
複数 Data を作るために使う。

**Warm 状態（s1 から配信）になるまでには Interest が複数回必要**である点に注意
（`pit_table` と同じ段階的配置。1 回目の Producer 応答だけでは s1 にはキャッシュされない）。

---

## 2. パケット形式

EtherType でパケット種別を区別する。

| EtherType | 名称 | 用途 |
|-----------|------|------|
| `0x88B5` | Interest | コンテンツ要求 |
| `0x88B6` | Data | コンテンツ応答（チャンク） |

### 2.1 Interest ヘッダ（ICNHeader）

| フィールド | 幅 | 意味 |
|------------|-----|------|
| `content_id` | 32 bit | コンテンツ識別子 |
| `type` | 16 bit | 上位プロトコル種別 |
| `flag` | 8 bit | エッジノード検出など |
| `hop_count` | 8 bit | ホップカウント |

### 2.2 Data ヘッダ（payload_t）

| フィールド | 幅 | 意味 |
|------------|-----|------|
| `content_id` | 32 bit | コンテンツ識別子 |
| `total_chunks` | 16 bit | **総チャンク数**（新規） |
| `chunk_id` | 16 bit | **チャンク番号**（0 始まり）（新規） |
| `flag` | 8 bit | 1 = スイッチへのキャッシュ提案 |
| `data` | 2048 bit（256 B） | ペイロード |

Consumer 側（`receive.py`）は `chunk_id` 順に `data` を連結して元ファイルを復元する。

---

## 3. スイッチ内部のデータ構造

### 3.1 Register（状態メモリ）

| Register | サイズ | 役割 |
|----------|--------|------|
| `content_cache` | 10240 × 2048 bit | チャンクデータ本体 |
| `pit_table` | 1024 × 9 bit | PIT（Interest の戻りポート） |
| `total_chunks_reg` | 1024 × 16 bit | コンテンツごとの総チャンク数 |

### 3.2 キャッシュのインデックス

1 コンテンツあたり最大 10 チャンク（256 B × 10 = 2.5 KB）を想定。

```
index = content_id × 10 + chunk_id
```

例: `content_id = 4`, `chunk_id = 0..3` → インデックス 40〜43

キャッシュヒット判定は **chunk 0 のスロット**（`content_id × 10`）が 0 でないかで行う。

### 3.3 Metadata（パイプライン内一時状態）

パケットヘッダには載らない内部状態。clone / recirculate 越しに引き継ぐ。

```p4
struct metadata {
    @field_list(FL_SERVE)   // FL_SERVE = 1
    bit<32> serve_content_id;
    @field_list(FL_SERVE)
    bit<16> serve_total;
    @field_list(FL_SERVE)
    bit<16> current_chunk;
    @field_list(FL_SERVE)
    bit<1>  serving_from_cache;
    @field_list(FL_SERVE)
    bit<1>  clear_cache_after_serve;
}
```

| フィールド | 意味 |
|------------|------|
| `serve_content_id` | 配信中の content_id |
| `serve_total` | 総チャンク数（例: 4） |
| `current_chunk` | **次に送る** chunk 番号（chunk 0 送信後は 1） |
| `serving_from_cache` | キャッシュ配信モード中か（後述 3.4） |
| `clear_cache_after_serve` | 全チャンク配信後に register を消すか（後述 3.5） |

`@field_list(1)` により、`clone_preserving_field_list` / `recirculate_preserving_field_list(1)` 呼び出し時も上記 5 フィールドが保持される。

### 3.4 `meta.serving_from_cache` とは

**「Consumer から来た新 Interest に初めて応える最中か、
recirculate で戻ってきた続きの処理中か」** を表す 1 bit フラグ。

| 値 | 意味 |
|----|------|
| `0` | 通常モード（Interest 転送、Data 転送・キャッシュ） |
| `1` | **キャッシュ配信モード**（1 Interest から複数 Data を返す最中） |

**いつ `1` になるか:** `begin_cache_serve()` でキャッシュヒット配信を開始するとき。

**いつ `0` になるか:**

- 全チャンク送信完了時（`queue_next_chunk_clone()` 内）
- Interest 転送（キャッシュミス）に入る直前

**Ingress での分岐:**

```p4
if (hdr.icn.isValid()) {
    if (meta.serving_from_cache == 1 && meta.current_chunk > 0) {
        continue_cache_serve();   // recirculate 後の「続き」
    } else {
        // 新規 Interest → キャッシュヒットなら begin_cache_serve()
    }
}
```

- `serving=1` かつ `current_chunk > 0` → **2 本目以降の Interest クローン**（続き処理）
- それ以外 → **Consumer からの新 Interest** または **chunk 0 の開始**

### 3.5 `meta.clear_cache_after_serve` とは

`pit_table` の「キャッシュヒット時、エッジ以外ならキャッシュを削除」を
**複数チャンク配信**に拡張したフラグ。

| 値 | 意味 |
|----|------|
| `0` | 配信後も register を保持（Consumer 直近のエッジ Interest: `icn.flag == 1`） |
| `1` | 全チャンク送信完了後に `clear_content_cache()` で register を消す |

**いつ `1` になるか:** `begin_cache_serve()` で **`hdr.icn.flag != 1`** のとき
（転送されてきた Interest。中継スイッチ間ではミス時に `icn.flag = 0` にされる）。

**いつ消去されるか:** `queue_next_chunk_clone()` で最終チャンク送信後
（clone ループ中は register から読み続ける必要があるため、**配信の最後**にまとめて削除）。

```p4
meta.clear_cache_after_serve = (hdr.icn.flag != 1) ? 1w1 : 1w0;
```

`clear_content_cache()` は `content_id × 10 + 0..9` の 10 スロットと
`total_chunks_reg` を 0 に戻す（chunk 0 クリアでヒット判定も false になる）。

---

## 4. 基本動作（3 つの処理パス）

Ingress の `apply` ブロックは、受信パケットの種類に応じて 3 経路に分岐する。

```
                    ┌─────────────────┐
                    │  パケット受信    │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
         Interest         Data          その他
              │              │
    ┌─────────┴────────┐     │
    │ キャッシュあり？  │     │ flag==1 なら cache_content()
    └─────────┬────────┘     │   → flag=0 にして転送
         Yes  │  No          │ その後 data_forward()
              │   └─ PIT 記録 → Interest 転送（clone なし）
              │
    begin / continue_cache_serve
    （後述セクション 6）
```

---

## 5. 初回取得時の動作（キャッシュミス → Producer 応答）

### 5.1 Interest の転送（キャッシュミス）— clone なし

```
h1:  Interest 送信
s1:  キャッシュなし → PIT 記録 → s2 へ転送（clone なし）
s2:  キャッシュなし → PIT 記録 → s3 へ転送（clone なし）
s3:  キャッシュなし → PIT 記録 → h2  へ転送（clone なし）
h2:  Interest 受信
```

Interest は **1 本だけ** が下流へ流れる。**どのスイッチでも clone は起きない。**

### 5.2 Producer からの Data（複数チャンク）

h2 の `send_content.py` は画像を 256 B ずつ分割し、**4 個の独立した Data パケット** として送信する。

```
Interest 1 本  →  Data 4 本（chunk_id = 0, 1, 2, 3）
```

各 Data は **別パケット** として s3 → s2 → s1 → h1 を通過する。
Producer 側は clone 不要で、普通の転送だけで動く。

### 5.3 中継スイッチでのキャッシュ（段階的配置）

Data パケットが Producer 側から Consumer 方向へ流れるとき、各スイッチで:

1. **`flag == 1` のときだけ** `cache_content()` を実行
2. `content_cache[index]` に 256 B を保存
3. `total_chunks_reg[content_id]` に総チャンク数を保存
4. **`hdr.payload.flag = 0` に書き換え**（下流はキャッシュしない）
5. `data_forward()` で PIT のポートへ転送

```p4
action cache_content() {
    content_cache.write(index, hdr.payload.data);
    total_chunks_reg.write(..., hdr.payload.total_chunks);
    hdr.payload.flag = 0;   // 下流には flag=0 の Data が流れる
}
```

初回 Producer 応答では **最も Producer に近い s3 だけ** が 4 チャンクをキャッシュする。

```
h2 ──Data(flag=1)──► s3 キャッシュ, flag→0 ──► s2 転送のみ ──► s1 転送のみ ──► h1
```

### 5.4 Interest 転送時の `icn.flag = 0`

キャッシュミスで Interest を下流へ転送するとき、**`hdr.icn.flag = 0`** にする。
これにより中継スイッチは「エッジノードからの要求」と区別できる。

Consumer（h1）は `send_interest.py` で **`icn.flag = 1`** を付けて送信する。

### 5.5 段階的キャッシュ移動（pit_table 型 + チャンク）

`pit_table` と同様、**Interest を重ねるたびにキャッシュが Consumer 側へ 1 ホップ移動**する。
chunk_table では各移動時に **4 チャンクすべて** が対象になる。

```
1 回目 Interest（ミス）:
  h2 → Data×4 → s3 のみキャッシュ（4/4）

2 回目 Interest:
  s3 ヒット → clone+recirculate で Data×4 を s2 方向へ（flag=1）
  s3 の register は配信完了後に clear
  s2 が Data×4 を受信・キャッシュ（4/4）

3 回目 Interest:
  s2 ヒット → 同様に Data×4 → s1 がキャッシュ（4/4）、s2 は clear

4 回目 Interest:
  s1 ヒット → clone+recirculate で h1 へ Data×4（h2 へ Interest 不要）
  s1 は icn.flag==1（エッジ）のためキャッシュを保持
```

| 回数 | キャッシュヒット | 配信後のキャッシュ保持 |
|------|------------------|------------------------|
| 1 | なし（Producer 応答） | s3 のみ |
| 2 | s3 | s2 のみ（s3 削除） |
| 3 | s2 | s1 のみ（s2 削除） |
| 4+ | s1 | s1 保持（Consumer 直近） |

**人気コンテンツほど Consumer 近くに配置される** ICN のインルーターキャッシュ動作を、
チャンク分割と clone ループと組み合わせて再現している。

---

## 6. キャッシュヒット時の動作（複数チャンク配信 + 段階的移動）

### 6.1 全体像

**Warm 状態（s1 にキャッシュ済み）** の例:

```
h1 ──Interest 1 本──► s1（キャッシュヒット）
h1 ◄──Data × 4──────── s1（register から生成）
                      s2, s3, h2 には Interest 未到達
```

**2 回目 Interest（s3 ヒット、キャッシュ移動）** の例:

```
h1 ──Interest──► s1 ──► s2 ──► s3（ヒット）
h1 ◄──Data×4── s1 ◄── s2 ◄── s3（register から生成、flag=1）
s2 が Data×4 をキャッシュ、s3 は配信後に register クリア
```

**clone するのはヒットした 1 台だけ**（s1, s2, s3 のいずれか）。
s2 でヒットすれば s2 だけが同様の内部ループを行う。

### 6.2 なぜ Data ではなく Interest を clone するか

clone しているのは **コンテンツのコピーではなく、「次のチャンクを送れ」という内部トリガ** である。
実データ 256 B は毎回 `serve_cached_chunk()` が register から読み出し、**Data として** 送る。

| 理由 | 説明 |
|------|------|
| Ingress 分岐 | 続き処理 `continue_cache_serve()` は **`hdr.icn.isValid()`** のときだけ入る |
| Data を clone すると | `payload` 経路に入り、前チャンクの再送や誤キャッシュになる |
| clone のタイミング | `begin`: serve **前**に clone。`continue`: serve **後**に clone（BMv2 I2E clone は ingress 開始時ヘッダをコピー） |
| Egress 分岐 | **`hdr.icn.isValid()`** な Interest だけ recirculate し、Data は h1 へ流す |

**Consumer から見えるのは Data だけ。Interest クローンはスイッチ外に出ない。**

### 6.3 1 ラウンドあたり「2 本」のイメージ

キャッシュヒットしたスイッチ内部で、**各 chunk ごと**に一時的に 2 本存在する。

```
Interest 1 本（Consumer から）
    │
    ├─ clone (I2E) ──► コピー A（Interest のまま）──► Egress
    │
    └─ 本体 B ──► serve_cached_chunk() で Data 化 ──► Egress

Egress:
  本体 B（Data）     → recirculate しない → ★ h1 へ送信
  コピー A（Interest）→ recirculate       → Ingress へ戻る（外に出さない）
```

**操作の対応:**

| 操作 | 場所 | 役割 |
|------|------|------|
| `clone_preserving_field_list(I2E, ...)` | **Ingress** | Interest をもう 1 本コピー |
| `recirculate_preserving_field_list(1)` | **Egress** | Interest コピーを送信せず Parser から再処理 |

`recirculate_preserving_field_list` は **v1model の extern**（`v1model.p4` で宣言、BMv2 simple_switch が実行）。
**Egress からしか呼べない。**

### 6.4 `current_chunk` の更新（clone コピーへの「+1」）

コピー側 Interest は **「次に送る chunk 番号」** を `meta.current_chunk` に持つ。
更新箇所は **初回と 2 回目以降で異なる**。

#### 初回: `begin_cache_serve()` — clone **前**に手動で `= 1`

```p4
if (meta.serve_total > 1) {
    meta.current_chunk = 1;                              // ★ clone 前にセット
    clone_preserving_field_list(CloneType.I2E, CLONE_SERVE_SESSION, FL_SERVE);
}
serve_cached_chunk(0, hdr.icn.content_id);               // 本体は chunk 0 を Data 化
data_forward();
```

順序が **clone → serve(0)** なので、コピーには「次は chunk 1」を載せるため
`serve_cached_chunk` の `chunk_id + 1` に頼る前に **明示的に `1` を代入**する。

#### 2 回目以降: `continue_cache_serve()` — serve **後**に `chunk_id + 1`

```p4
action continue_cache_serve() {
    serve_cached_chunk(meta.current_chunk, meta.serve_content_id);  // 送信
    data_forward();
    queue_next_chunk_clone();                                       // その後 clone
}

action serve_cached_chunk(...) {
    ...
    meta.current_chunk = chunk_id + 1;   // ★ 124 行目
}
```

順序が **serve → clone** なので、`serve_cached_chunk` 末尾の加算で
次ラウンド用の `current_chunk` が clone に載る。

**BMv2 I2E clone の仕様:** クローンの **ヘッダ** は ingress 開始時（Interest のまま）、
**metadata（field_list）** は clone 呼び出し時点の値。`continue` でも
serve 後に clone を呼んでも、クローン側は Interest として egress に載り recirculate できる。

#### 4 チャンクの具体例

| ラウンド | 処理 | clone 時の `current_chunk` | h1 へ送る Data |
|----------|------|------------------------------|----------------|
| 1 | `begin`: **148行で `=1`** → clone → serve(0) | **1** | chunk 0 |
| 2 | `continue`: serve(1) → **124行で `=2`** → clone | **2** | chunk 1 |
| 3 | serve(2) → `=3` → clone | **3** | chunk 2 |
| 4 | serve(3) → `=4` → clone なし | — | chunk 3 |

### 6.5 時系列（4 チャンク、s1 キャッシュヒット）

Consumer Interest **1 本**に対し、s1 内部で Ingress が **4 段**走る。

```
═══════════════════════════════════════════════════════════════
【第1ラウンド】Consumer から来た本物 Interest
═══════════════════════════════════════════════════════════════
  Ingress: begin_cache_serve()
    PIT[4] = h1 方向ポート
    meta.serving=1, serve_total=4
    meta.current_chunk = 1  →  clone(Interest)     ← コピー A
    serve_cached_chunk(0)   →  Data chunk 0       ← 本体 B
    data_forward()

  Egress:
    本体 B (Data)      → ★ h1 へ chunk 0 送信
    コピー A (Interest)→ recirculate → Ingress へ

═══════════════════════════════════════════════════════════════
【第2ラウンド】recirculate 後（serving=1, current_chunk=1）
═══════════════════════════════════════════════════════════════
  Ingress: continue_cache_serve()
    serve_cached_chunk(1) → current_chunk=2 → clone
    data_forward()
  Egress:
    Data chunk 1 → ★ h1
    Interest clone → recirculate

═══════════════════════════════════════════════════════════════
【第3・第4ラウンド】同様
═══════════════════════════════════════════════════════════════
  chunk 2 → h1、chunk 3 → h1（最終。clone なし、PIT クリア、serving=0、必要なら register クリア）
```

**パケット数の整理（s1 ヒット、4 チャンク）:**

| 種別 | 本数 | 外部への出入り |
|------|------|----------------|
| Consumer → s1 Interest | 1 | 外部 |
| s1 内部 Interest clone | 3 | **外部に出ない** |
| s1 → h1 Data | 4 | 外部 |

### 6.6 BMv2 上の制約と採用方式

1 回の Ingress だけでは複数 Data を順に外部送信できない。

| 方式 | 問題 |
|------|------|
| `resubmit` 連鎖（Ingress） | 同期的ネスト。最後の 1 チャンクだけ egress |
| `recirculate` 連鎖（Egress） | 同上 |
| clone → port **511** | BMv2 では **drop ポート**（`default_drop_port = 511`）で破棄 |

**採用: Ingress `clone` + Egress `recirculate`**

- 本体: Interest → Data に変換 → **通常 egress で h1 へ**
- コピー: Interest のまま egress → **recirculate で内部ループ**

### 6.7 各アクションの役割（コード対応）

| アクション | 呼ばれる条件 | 主な処理 |
|------------|--------------|----------|
| `cache_content` | Data + `flag==1` | register 書込、`flag=0` |
| `begin_cache_serve` | 新 Interest + キャッシュヒット | PIT、`serving=1`、`clear_cache_after_serve` 設定、clone、chunk 0 送信 |
| `continue_cache_serve` | Interest + `serving=1` + `current_chunk>0` | chunk N 送信、残りがあれば clone |
| `serve_cached_chunk` | 上記から | register 読出し、Interest→Data（`flag=1`）、`current_chunk=chunk_id+1` |
| `queue_next_chunk_clone` | 上記から | 未送信があれば I2E clone、なければ register クリア・`serving=0` |
| `clear_content_cache` | 非エッジ配信完了時 | 10 スロット + `total_chunks_reg` を 0 |
| `data_forward` | Data 送信時 | PIT 参照、最終 chunk で PIT クリア |

### 6.8 Egress の recirculate 条件

```p4
if (meta.serving_from_cache == 1
    && hdr.icn.isValid()              // Interest クローンのみ
    && meta.current_chunk > 0
    && meta.current_chunk < meta.serve_total) {
    recirculate_preserving_field_list(FL_SERVE);
}
```

- **Data**（`icn` 無効）→ 条件 false → **h1 へ送信**
- **Interest クローン** → recirculate → Ingress へ（Consumer には届かない）

### 6.9 Clone Session 設定

各スイッチの `*-runtime.json` に clone session 100 を定義。
egress ポートは clone パケットを egress パイプラインに載せるための設定。
Interest クローンは Egress で recirculate されるため、**最終的に Consumer へは出ない**。

（旧設定の port 511 は drop ポートのため使用不可。）

---

## 7. 具体例: image4.png（1024 B、4 チャンク）

| 項目 | 値 |
|------|-----|
| ファイルサイズ | 1024 B |
| チャンクサイズ | 256 B |
| 総チャンク数 | 4 |
| content_id | 4 |
| キャッシュインデックス | 40, 41, 42, 43 |

### 7.1 1 回目（Cold）— Producer 応答、clone なし

| 段階 | 動作 |
|------|------|
| Interest | h1 → s1 → s2 → s3 → h2（**clone なし**、`icn.flag` は途中で 0） |
| Data × 4 | h2 が独立 4 パケット送信 → s3 → s2 → s1 → h1 |
| キャッシュ | **s3 のみ 4/4**（s1/s2 は `flag=0` の Data のため非キャッシュ） |
| h1 | 4 チャンク受信 → 画像復元 |

### 7.2 2 回目 — s3 ヒット、キャッシュ s3→s2

| 段階 | 動作 |
|------|------|
| Interest | h1 → s1 → s2 → **s3 でヒット** |
| 内部 | s3 が clone+recirculate で Data × 4 生成（`flag=1`） |
| キャッシュ | s3 register **クリア**、s2 が Data×4 から **4/4 キャッシュ** |
| h1 | 4 チャンク受信 |

### 7.3 3 回目 — s2 ヒット、キャッシュ s2→s1

| 段階 | 動作 |
|------|------|
| Interest | h1 → s1 → **s2 でヒット** |
| 内部 | s2 が clone+recirculate で Data × 4 生成 |
| キャッシュ | s2 register **クリア**、s1 が **4/4 キャッシュ** |
| h1 | 4 チャンク受信 |

### 7.4 4 回目（Warm）— s1 ヒット、Producer 不要

| 段階 | 動作 |
|------|------|
| Interest | h1 → **s1 でヒット**（s2/s3/h2 未到達） |
| 内部 | s1 が clone+recirculate で Data × 4 生成 |
| キャッシュ | s1 は **`icn.flag==1` のため保持** |
| h1 | 4 チャンク受信 → 同一 MD5 の画像を復元 |

---

## 8. PIT（Pending Interest Table）の扱い

| タイミング | 操作 |
|------------|------|
| Interest 転送時（ミス） | `pit_table[content_id] = ingress_port` |
| キャッシュヒット時（配信開始） | 同上（戻り先を記録） |
| 最終 Data チャンク転送時 | `pit_table[content_id] = 0`（クリア） |

PIT は **content_id 単位** で 1 エントリ。
複数チャンクすべて同じ PIT エントリ（戻りポート）を参照して Consumer 方向へ転送する。

---

## 9. 制約と今後の拡張

### 9.1 現在の制約

| 制約 | 内容 |
|------|------|
| チャンク数上限 | 1 コンテンツ **10 チャンク**（約 2.5 KB） |
| チャンクサイズ | 固定 256 B |
| ターゲット | BMv2 v1model 専用（clone / recirculate 依存） |
| キャッシュ置換 | なし（register 上書きのみ） |

### 9.2 今後の改善方向

1. **キャッシュ置換**: LRU 等（register サイズ制約下）
2. **大コンテンツ対応**: 10 チャンク上限の拡大、`image5.png` 等
3. **ハードウェア移植**: Tofino 等では recirculate / clone の挙動を再検証

### 9.3 pit_table との差分（発表用まとめ）

| 項目 | pit_table | chunk_table（本実装） |
|------|---------|----------------------|
| Data サイズ | 256 B 固定 1 パケット | 256 B × N チャンク |
| キャッシュ粒度 | content_id 1 スロット | content_id × 10 + chunk_id |
| キャッシュ配置 | 要求ごとに Consumer 側へ移動（flag 制御） | **同左**（chunk 単位で段階移動） |
| キャッシュヒット時 | 1 Data | **clone+recirculate で N Data** |
| 非エッジヒット時 | register 即削除 | **N チャンク配信後に register 一括削除** |
| 大きいコンテンツ | 非対応 | 分割転送に対応（現状 ~2.5 KB/コンテンツ） |

---

## 10. 検証方法

自動実験スクリプト: `run_chunk_experiment.py`

```bash
cd chunk_table
make build
sudo PATH=/home/p4/src/p4dev-python-venv/bin:$PATH python3 run_chunk_experiment.py
```

### 確認項目

1. **Phase 1（初回）**: h2 が 4 チャンク送信、h1 が画像復元、**s3 のみ 4/4 キャッシュ**（s1/s2 は 0）
2. **Phase 2（移動）**: Interest 2 回で s3→s2→s1 とキャッシュ移動、各段階で下流側 register クリア
3. **Phase 3（Warm）**: h2 へ Interest 未到達、s1 キャッシュから 4 チャンク配信、h1 が画像復元
4. MD5 がオリジナル `image4.png` と一致

---

## 11. 発表用スライド構成案

1. **背景**: ICN + インルーターキャッシュ、256 B 制約と大コンテンツ問題
2. **提案**: チャンク分割 + flag 制御による段階的配置 + 複数 Data 返却
3. **データ構造**: register インデックス、PIT、metadata（`serving_from_cache`, `clear_cache_after_serve`）
4. **初回取得**: Interest 転送 → Producer が Data×N → **下流 1 台のみキャッシュ**
5. **段階的配置**: `flag=0` / `icn.flag`、Interest ごとの s3→s2→s1 移動
6. **キャッシュヒット**: clone+recirculate、非エッジ時の register クリア
7. **なぜ Interest clone か**: Data は外へ、Interest は内部トリガ
8. **BMv2 制約**: resubmit/511 が使えない理由
9. **評価**: image4、Cold→移動→Warm、15 チェック PASS
10. **今後**: チャンク上限拡大、キャッシュ置換

---

## 参考: 関連ファイル

| ファイル | 役割 |
|----------|------|
| `switch.p4` | P4 データプレーン（本ドキュメントの対象） |
| `s1-runtime.json` 等 | Interest 転送テーブル、clone session |
| `send_interest.py` | Consumer: Interest 送信 |
| `send_content.py` | Producer: Interest 受信 → チャンク分割 Data 送信 |
| `receive.py` | Consumer: チャンク受信 → ファイル再構成 |
| `run_chunk_experiment.py` | 自動検証 |
| `../pit_table/switch.p4` | 単一チャンク + flag 制御の参照実装 |
| `../METHODOLOGY.md` | ICN vs IP 比較実験の共通手法 |

## 参考: v1model extern

| extern | 宣言 | 呼び出し可能 | 本実装での用途 |
|--------|------|--------------|----------------|
| `clone_preserving_field_list` | `v1model.p4` | Ingress / Egress | 次チャンク用 Interest コピー |
| `recirculate_preserving_field_list` | `v1model.p4` | **Egress のみ** | Interest コピーを内部ループ |
| `resubmit_preserving_field_list` | `v1model.p4` | **Ingress のみ** | 採用せず（ネスト問題） |

実行時実装: BMv2 `behavioral-model/targets/simple_switch/simple_switch.cpp`
