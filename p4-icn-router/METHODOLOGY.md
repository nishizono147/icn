# コンテンツ取得時間の計測・比較手法

研究発表用メモ。ICN（`pit_table`）と IP ベースライン（`ip_baseline`）の
実験設計・計測方法・比較の仕方をまとめる。

---

## 1. 研究の目的

**同じネットワーク条件**のもとで、

- **ICN（PIT + キャッシュ）** と
- **従来型 IP ルーティング**

の **コンテンツ取得時間** を測定し、ICN のキャッシュ効果を定量評価する。

---

## 2. 実験環境（両方式で共通）

| 項目 | 内容 |
|------|------|
| **トポロジ** | `h1 ─ s1 ─ s2 ─ s3 ─ h2`（3 ホップ） |
| **Consumer** | h1（10.0.1.1） |
| **Producer** | h2（10.0.2.2） |
| **スイッチ** | BMv2 + P4（Mininet 上） |
| **コンテンツ** | `image1.png` 等（約 200〜250 B） |
| **ペイロード上限** | **256 バイト**（ICN Data と揃える） |
| **試行回数** | 10 回連続（間隔 0.2 秒） |

ICN と IP で変えるのは **スイッチの P4 プログラム** と **ホスト側プロトコル** のみ。
トポロジ・画像・データサイズは揃えている。

---

## 3. 2 つの方式

### ICN（`pit_table`）

```
h1 --Interest--> s1 --> s2 --> s3 --> h2
h1 <--Data------- s1 <-- s2 <-- s3 <-- h2
```

| 項目 | 内容 |
|------|------|
| 要求 | Interest（EtherType 0x88B5）+ `content_id` |
| 応答 | Data（EtherType 0x88B6）+ 256 B データ |
| スイッチ | PIT（戻り経路）+ コンテンツキャッシュ |
| 2 回目以降 | 中継スイッチでキャッシュヒット → **Producer まで行かない** |

### IP ベースライン（`ip_baseline`）

```
h1 --UDP 要求--> s1 --> s2 --> s3 --> h2
h1 <--UDP 応答-- s1 <-- s2 <-- s3 <-- h2
```

| 項目 | 内容 |
|------|------|
| 要求 | UDP port 9999: `content_id` + `flag` + `hop_count` |
| 応答 | UDP port 9999: `content_id` + `flag` + 256 B データ |
| スイッチ | IPv4 L3 転送のみ（キャッシュなし） |
| 毎回 | **h2 まで到達**（Warm でも変化なし） |

HTTP/TCP は使わない（TCP ハンドシェイク等のオーバーヘッドを除くため）。
UDP 1 要求 → 1 応答で ICN の Interest/Data に構造を揃えている。

---

## 4. 「コンテンツ取得時間」の定義

**Consumer（h1）から見た、要求送信から応答データ受信までの時間**と定義する。

| 方式 | 開始 | 終了 |
|------|------|------|
| **ICN** | Interest パケットの pcap 時刻 | 対応する Data パケットの pcap 時刻 |
| **IP** | UDP 要求パケットの pcap 時刻 | 対応する UDP 応答パケットの pcap 時刻 |

いずれも **「要求 1 本 → 応答 1 本」** の往復時間を測る。

---

## 5. 計測方法

### なぜ pcap（tcpdump）か

初期実装では Scapy のパケット受信コールバックで計測していたが、
ユーザ空間の処理遅延により Warm 期に大きなばらつき（7〜80 ms）が発生した。

**tcpdump の pcap タイムスタンプ**（カーネルがパケットを捕まえた時刻）を用いる方式に変更した。

### 手順

```
計測開始前: tcpdump を 1 本だけ起動（全試行共通）
各試行:     要求送信 → pcap から「要求→応答」の時刻差を読み取る
計測終了後: tcpdump 停止
```

### 1 試行の流れ

```
  h1                          ネットワーク                    h2
   |  ① 要求送信 (Interest / UDP request)                      |
   | --------------------------------------------------------> |
   |                          ③ P4 転送 (+ ICN ならキャッシュ) |
   |  ④ 応答受信 (Data / UDP response)                         |
   | <-------------------------------------------------------- |

取得時間 = ④の pcap 時刻 − ①の pcap 時刻
```

### 実装

| 方式 | スクリプト | pcap フィルタ |
|------|-----------|---------------|
| ICN | `pit_table/benchmark_icn.py` | EtherType 0x88B5 / 0x88B6 |
| IP | `ip_baseline/benchmark_ip.py` | UDP port 9999 |

---

## 6. 試行手順（Pattern A）

**同一 Mininet セッション内で、同じ `content_id` を 10 回連続**リクエストする。

| 試行 | ICN での意味 | IP での意味 |
|------|-------------|------------|
| **trial 1** | **Cold**（キャッシュなし、h2 まで） | **Cold**（h2 まで） |
| **trial 2〜3** | キャッシュが s3 → s2 → s1 と順に移動 | 毎回 h2（変化なし） |
| **trial 4〜10** | **Warm**（s1 キャッシュヒット） | 毎回 h2（変化なし） |

### 実行コマンド

**ICN（pit_table）**

```bash
cd p4-icn-router/pit_table && make
# h2
python3 send_content.py --quiet
# h1
python3 benchmark_icn.py 1
```

**IP（ip_baseline）**

```bash
cd p4-icn-router/ip_baseline && make
# h2
python3 serve_content.py --quiet
# h1
python3 benchmark_ip.py 1
```

---

## 7. 比較の仕方

### 主比較: Cold 同士

| | ICN | IP |
|--|-----|-----|
| **比較対象** | trial 1 | trial 1（または 10 回平均） |
| **経路** | どちらも h2 まで | どちらも h2 まで |
| **意味** | キャッシュなしの基本性能 | 従来 IP の基本性能 |

→ **公平なベースライン比較**

### 副比較: ICN のキャッシュ効果（IP とは別枠）

| | ICN trial 1 | ICN trial 4+ |
|--|-------------|--------------|
| **経路** | h2 まで | s1 で応答（h2 不要） |
| **意味** | Cold | Warm（中継キャッシュ） |

→ **ICN 独自の利点**として別グラフ・別表で示す。
IP の Warm 平均と直接比較しない（IP に中継キャッシュがないため）。

### 報告例

```
表1: Cold 取得時間（content_id=1）
  ICN trial 1:        24 ms
  IP  trial 1:        33 ms
  IP  全試行平均:     27 ms

表2: ICN キャッシュ効果
  ICN trial 1 (cold):   24 ms
  ICN trial 4+ (warm):   2 ms  （約 12 倍高速化）
```

---

## 8. 結果の読み方（期待される傾向）

```
取得時間 (ms)
  ^
  |  ● IP (毎回 ~25-30 ms, 横ばい)
  |
  |  ● ICN Cold (~25-35 ms)
  |
  |      ○ ICN Warm (~2-5 ms)
  +---------------------------------> 試行回数
       1    2    3    4 ... 10
```

- **Cold**: ICN ≒ IP（どちらも h2 まで行く）
- **Warm**: ICN のみ大幅短縮（中継キャッシュ）
- **IP**: 試行を重ねてもほぼ一定

---

## 9. 限界・注意点

1. **Mininet + BMv2** はソフトウェア実装 → 絶対値より **相対比較** を重視
2. **pcap タイムスタンプ** は μs 精度。ごく短い Warm 値（0〜2 ms）は **計測下限付近** と注記する
3. TX/RX の記録タイミング差で負の差分が出ることがあり、`max(0, ...)` で 0 ms と表示される場合がある
4. ICN は **L2 カスタム**、IP は **L3 UDP** — 完全同一プロトコルではないが、1 要求 1 応答・同サイズで揃えた
5. 画像が **256 B 以下**と小さい — 大容量コンテンツでの評価は今後の課題
6. ICN Warm は **1 content_id 固定**の連続試行 — 複数 Consumer や複数コンテンツは未評価

---

## 10. 発表用 1 スライド要約

> **手法:** 同一トポロジ・同一画像・256 B ペイロードで、ICN（PIT+キャッシュ）と
> IP（UDP+L3 転送）のコンテンツ取得時間を Mininet 上で比較した。
>
> **計測:** h1 の tcpdump pcap タイムスタンプにより、要求パケットから応答パケットまでの
> 時間を 10 回連続計測。
>
> **比較:** Cold（ICN trial 1 vs IP trial 1）で基本性能を比較。
> ICN Warm（trial 4+）は中継キャッシュ効果として別途報告。
>
> **結果:** Cold では ICN ≒ IP。ICN Warm では中継キャッシュにより取得時間が大幅短縮。

---

## 関連ファイル

| パス | 説明 |
|------|------|
| `pit_table/benchmark_icn.py` | ICN 取得時間計測 |
| `pit_table/send_content.py` | ICN Producer |
| `ip_baseline/benchmark_ip.py` | IP 取得時間計測 |
| `ip_baseline/serve_content.py` | IP Producer（UDP） |
| `ip_baseline/udp_content.py` | UDP 要求/応答フォーマット |
| `pit_table/BENCHMARK_FINDINGS.md` | 計測改善の経緯（Scapy → pcap） |
