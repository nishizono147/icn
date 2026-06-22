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
2. **中継スイッチ（s1, s2, s3）すべて**にチャンク単位でキャッシュする
3. **2 回目以降の Interest** は、最寄りのキャッシュを持つスイッチが
   **複数 Data パケット** として Consumer へ返す（Producer へは行かない）

### 1.2 ネットワーク構成

```
h1 (Consumer) ─ s1 ─ s2 ─ s3 ─ h2 (Producer)
     10.0.1.1              10.0.2.2
```

- ホップ数: 3（Consumer から Producer まで）
- スイッチ: BMv2 + P4_16（v1model）
- 検証例: `image4.png`（1024 B → **4 チャンク**）

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

キャッシュからの複数チャンク配信時に、clone / recirculate 越しに引き継ぐ。

| フィールド | 意味 |
|------------|------|
| `serve_content_id` | 配信中の content_id |
| `serve_total` | 総チャンク数 |
| `current_chunk` | 次に送るチャンク番号 |
| `serving_from_cache` | キャッシュ配信モード中フラグ |

`@field_list(1)` により、clone / recirculate 時もこれらが保持される。

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
    └─────────┬────────┘     │ その後 data_forward()
         Yes  │  No          │
              │   └─ PIT 記録 → Interest 転送
              │
    キャッシュから複数チャンク配信
    （後述セクション 6）
```

---

## 5. 初回取得時の動作（キャッシュミス → Producer 応答）

### 5.1 Interest の転送（キャッシュミス）

1. chunk 0 がキャッシュにない → ミス
2. `pit_table[content_id] = ingress_port`（戻り先ポートを記録）
3. `forward_interest` テーブルで次ホップへ Interest を転送
4. 最終的に h2（Producer）が Interest を受信

### 5.2 Producer からの Data（複数チャンク）

h2 の `send_content.py` は画像を 256 B ずつ分割し、**4 個の独立した Data パケット** として送信する。

```
Interest 1 本  →  Data 4 本（chunk_id = 0, 1, 2, 3）
```

各 Data パケットは独立してスイッチを通過するため、BMv2 上でも問題なく転送できる。

### 5.3 中継スイッチでのキャッシュ（全スイッチ）

Data パケットが Producer 側から Consumer 方向へ流れるとき、各スイッチで:

1. `flag == 1` なら `cache_content()` を実行
2. `content_cache[index]` に 256 B を保存
3. `total_chunks_reg[content_id]` に総チャンク数を保存
4. `data_forward()` で PIT のポートへ転送

**重要:** `cache_content()` 実行後も **`flag` を 0 にしない**。
これにより s3 だけでなく、s2 → s1 と下流の中継スイッチも同じ Data をキャッシュできる。

```
h2 ──Data(flag=1)──► s3 キャッシュ ──► s2 キャッシュ ──► s1 キャッシュ ──► h1
```

最終チャンク（`chunk_id + 1 == total_chunks`）転送時に PIT エントリをクリアする。

---

## 6. 2 回目以降の動作（キャッシュヒット → 複数チャンク配信）

### 6.1 全体像

Consumer が同じ `content_id` で Interest を再送すると、
**最寄りのキャッシュを持つスイッチ**（通常は s1）で処理が完結する。

```
h1 ──Interest──► s1（キャッシュヒット）
h1 ◄──Data×4──── s1（キャッシュから chunk 0〜3 を返す）
                 s2, s3, h2 には Interest が届かない
```

### 6.2 なぜ「1 Interest → 複数 Data」が難しいか

BMv2（v1model）では、1 回の Ingress 処理の中で複数パケットを
順番に「外部へ」送る標準的な方法がない。

| 方式 | 問題 |
|------|------|
| `resubmit` を連鎖 | 同期的にネストされ、**最後の 1 チャンクだけ**が egress する |
| `recirculate` を連鎖 | 同上。途中のチャンクが送信されない |
| egress port 511 | BMv2 では **drop ポート**であり、パケットが破棄される |

### 6.3 採用した方式: Ingress Clone + Egress Recirculate

**核心アイデア:**

- **Data パケット**（実データ）は普通に egress して Consumer へ送る
- **Interest クローン**（制御用）は egress で `recirculate` し、
  スイッチ内部で再度 Ingress に戻して「次のチャンク」を生成する

これにより、各 Data チャンクは **独立した egress** として送信される。

### 6.4 処理の流れ（4 チャンクの例）

Interest 受信（s1、キャッシュヒット）からの流れ:

```
[Ingress] begin_cache_serve()
  ├─ PIT に戻りポートを記録
  ├─ clone(Interest) ────────────────┐  残りチャンク用の制御パケット
  ├─ chunk 0 を Data 化             │
  └─ data_forward() → egress ───────┼──► h1 へ Data (chunk 0) 送信
                                      │
[Egress] clone された Interest       │
  └─ recirculate() ──────────────────┘
         │
         ▼
[Ingress] continue_cache_serve()  （meta.current_chunk = 1）
  ├─ clone(Interest)
  ├─ chunk 1 を Data 化
  └─ data_forward() → egress ───────► h1 へ Data (chunk 1) 送信
         │
        （以下、chunk 2, 3 も同様に繰り返し）
         │
[Ingress] continue_cache_serve()  （meta.current_chunk = 3）
  ├─ chunk 3 を Data 化（最終）
  ├─ data_forward() → PIT クリア
  └─ clone なし（配信完了）
```

### 6.5 各アクションの役割

| アクション | 実行タイミング | 処理内容 |
|------------|----------------|----------|
| `begin_cache_serve` | 新規 Interest がキャッシュヒット | PIT 記録、状態初期化、chunk 0 送信、残りがあれば clone |
| `continue_cache_serve` | recirculate 後の Interest（続き） | 現在の chunk 番号を Data 化して転送、残りがあれば clone |
| `serve_cached_chunk` | 上記から呼ばれる | register からデータ読み出し、Interest → Data ヘッダ変換 |
| `queue_next_chunk_clone` | 上記から呼ばれる | 未送信チャンクがあれば I2E clone、なければ状態クリア |
| `data_forward` | Data 送信時 | PIT 参照で egress ポート決定、最終チャンクで PIT クリア |

### 6.6 Egress の recirculate 条件

Interest クローンだけを内部ループさせ、Data を Consumer に流す。

```p4
if (serving_from_cache == 1
    && hdr.icn.isValid()          // Interest クローンのみ
    && current_chunk > 0
    && current_chunk < serve_total)
    recirculate_preserving_field_list(1);
```

- **Data パケット**（`icn` 無効）→ recirculate しない → そのまま h1 へ送信
- **Interest クローン** → recirculate → Ingress で次チャンクを生成

### 6.7 Clone Session 設定

各スイッチの runtime JSON に clone session 100 を定義する。
egress ポートは recirculate 前のパイプライン通過用であり、
Interest クローンは Egress で recirculate されるため Consumer には届かない。

---

## 7. 具体例: image4.png（1024 B、4 チャンク）

| 項目 | 値 |
|------|-----|
| ファイルサイズ | 1024 B |
| チャンクサイズ | 256 B |
| 総チャンク数 | 4 |
| content_id | 4 |
| キャッシュインデックス | 40, 41, 42, 43 |

### 7.1 初回（Cold）

| 段階 | 動作 |
|------|------|
| Interest | h1 → s1 → s2 → s3 → h2 |
| Data × 4 | h2 → s3 → s2 → s1 → h1（各スイッチが 4 チャンクすべてキャッシュ） |
| h1 | 4 チャンク受信 → 再構成 → `received_image/image4.png` |

### 7.2 2 回目（Warm）

| 段階 | 動作 |
|------|------|
| Interest | h1 → **s1 でキャッシュヒット**（s2/s3/h2 へ未到達） |
| Data × 4 | s1 の register から chunk 0〜3 を生成して h1 へ返却 |
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

`image5.png`（約 3.2 MB）のような大ファイルは、
現行の register サイズでは中継キャッシュの対象外。
Producer からの直接配信（チャンク分割送信）には対応可能。

### 9.2 pit_table との差分（発表用まとめ）

| 項目 | pit_table | chunk_table（本実装） |
|------|---------|----------------------|
| Data サイズ | 256 B 固定 1 パケット | 256 B × N チャンク |
| キャッシュ粒度 | content_id 1 スロット | content_id × 10 + chunk_id |
| 中継キャッシュ | 実質 Producer 側のみ | **全中継スイッチ** |
| キャッシュヒット時 | 1 Data を返す | **複数 Data を clone+recirculate で返す** |
| 大きいコンテンツ | 非対応 | 分割転送に対応 |

---

## 10. 検証方法

自動実験スクリプト: `run_chunk_experiment.py`

```bash
cd chunk_table
make build
sudo PATH=/home/p4/src/p4dev-python-venv/bin:$PATH python3 run_chunk_experiment.py
```

### 確認項目

1. **Phase 1（初回）**: h2 が 4 チャンク送信、h1 が画像復元、全スイッチ 4/4 キャッシュ
2. **Phase 2（2 回目）**: h2 へ Interest 未到達、s1 キャッシュから 4 チャンク配信、h1 が画像復元
3. MD5 がオリジナル `image4.png` と一致

---

## 11. 発表用スライド構成案

1. **背景**: ICN + インルーターキャッシュ、256 B 制約と大コンテンツ問題
2. **提案**: チャンク分割 + 中継スイッチキャッシュ + 複数 Data 返却
3. **データ構造**: register インデックス、PIT、metadata
4. **初回取得**: Interest 転送 → 複数 Data → 全スイッチキャッシュ
5. **キャッシュヒット**: s1 で完結、clone + recirculate による 4 Data 生成
6. **BMv2 実装上の工夫**: なぜ resubmit ではなく clone+recirculate か
7. **評価**: image4 4 チャンク、Cold/Warm 比較、MD5 一致
8. **制約と今後**: 10 チャンク上限、置換ポリシー、ハードウェア実装

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
| `../METHODOLOGY.md` | ICN vs IP 比較実験の共通手法 |
