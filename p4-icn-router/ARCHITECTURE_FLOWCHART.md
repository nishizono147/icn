# 過渡期 ICN アーキテクチャ フローチャート

`設計メモ.txt` に記載の IP オーバーレイ ICN（IWP）設計を図示したもの。
Mermaid 対応ビューア（GitHub、VS Code 等）でレンダリングできる。

---

## 1. 全体構成

```mermaid
flowchart TB
    subgraph hosts["ホスト"]
        C[Consumer]
        P[Producer]
    end

    subgraph network["混在ネットワーク"]
        IWP1["IWP\n(ICN + キャッシュ)"]
        IPR["IP ルータ\n(ICN 非対応)"]
        IWP2["IWP\n(ICN + キャッシュ)"]
    end

    NRS[("NRS サーバー\n(iwpid → IP アドレス)")]

    C -->|"Interest / Data"| IWP1
    IWP1 <-->|"L2 直結 or IP"| IPR
    IPR <-->|"IP 転送のみ"| IWP2
    IWP2 --> P

    IWP1 -.->|"非隣接 IWP 宛"| NRS
    IWP2 -.->|"非隣接 IWP 宛"| NRS

    style IWP1 fill:#e8f4fc,stroke:#2980b9
    style IWP2 fill:#e8f4fc,stroke:#2980b9
    style IPR fill:#fdebd0,stroke:#e67e22
    style NRS fill:#eafaf1,stroke:#27ae60
```

**要点:** 全ルータを IWP に置き換えられない過渡期のため、IP ルータを挟んでも
Interest / Data が到達できるよう IP 層でカプセル化する。

---

## 2. パケット構造

### 2.1 積層構成（L1 → L2 → IP → ICN）

![パケット構成](architecture_packet_structure.png)

![各装置が参照するレイヤ](architecture_packet_layers.png)

PNG 再生成: `python3 generate_packet_structure.py`

```mermaid
block-beta
    columns 1

    block:phy["L1 物理層"]:1
        p1["ケーブル / 光ファイバ（ビット伝送）"]
    end

    block:l2["L2 データリンク層（Ethernet 14B）"]:1
        columns 3
        macdst["dst MAC\n6B"]
        macsrc["src MAC\n6B"]
        eth["EtherType\n0x0800"]
    end

    block:ip["L3 IP層（IPv4 20B）"]:1
        columns 2
        ipfix["固定部\nVer, TTL, Proto=ICN, Checksum ..."]
        ipaddr["src IP | dst IP\n(次ホップ IWP / Consumer)"]
    end

    block:icnfix["ICN層・固定ヘッダ 16B"]:1
        columns 4
        cid["content_id"]
        meta["type | flags | hop_limit"]
        cip["consumer_ip"]
        chk["chunk_id | name_len"]
    end

    block:icnvar["ICN層・可変部"]:1
        columns 2
        name["Interest:\nコンテンツ名"]
        data["Data:\nチャンクペイロード"]
    end
```

| レイヤ | 誰が処理するか | 設計メモでの役割 |
|--------|---------------|-----------------|
| **L1 物理** | 物理装置 | ビット伝送 |
| **L2 Ethernet** | L2 スイッチ / IWP | 隣接 IWP 間は NMT でポート直出力も可 |
| **L3 IPv4** | **IP ルータ + IWP** | IP ルータはここまで（ICN は透過転送） |
| **ICN 固定** | **IWP のみ** | PIT / LCST / ECST / FIB の制御情報 |
| **ICN 可変** | **IWP のみ** | コンテンツ名（Interest）または Data 本体 |

### 2.2 Interest と Data の違い（ICN 可変部）

| パケット | type | ICN 可変部 |
|---------|------|-----------|
| **Interest** | `0x0001` | コンテンツ名（FIB LPM / ECST 完全一致キー） |
| **Data** | `0x0010` | チャンクデータ（256B 等）+ chunk_id |

**共通:** `consumer_ip` は ICN 固定ヘッダに保持 → Data 返送時の IP カプセル化に使用（設計メモ L7）。

### 2.3 Phase 1 との差（参考）

| | Phase 1 (`chunk_table`) | Phase 2（本設計） |
|--|------------------------|-------------------|
| L2 | EtherType `0x88B5` で ICN 直載せ | EtherType `0x0800`（IPv4） |
| IP 層 | なし | **あり**（IP ルータ透過転送） |
| ICN 層 | 64bit 固定 | 128bit 固定 + 可変 Name |

---

## 3. IWP 内部テーブル

```mermaid
flowchart LR
    subgraph tables["IWP テーブル群"]
        PIT["PIT\n(Interest 受信ポート)"]
        LCST["LCST\n(ローカルキャッシュ\n= on-path)"]
        ECST["ECST\n(近隣 IWP キャッシュ情報\n= off-path)"]
        FIB["FIB\n(コンテンツ名 LPM\n→ 次ホップ iwpid)"]
        NMT["NMT\n(隣接 iwpid\n→ 出力ポート)"]
    end

    subgraph external["外部"]
        NRS2[("NRS\n(iwpid → IP)")]
    end

    NMT -->|"非隣接"| NRS2
```

| テーブル | キー | 値 | 構築方法 |
|---------|------|-----|---------|
| **PIT** | コンテンツ名 | 受信ポート | Interest 受信時に記録 |
| **LCST** | コンテンツ名 | コンテンツデータ | Data 通過時、キャッシュ提案 flag=1 |
| **ECST** | コンテンツ名 | キャッシュ保有 iwpid | 近隣 IWP からの定期通知 |
| **FIB** | コンテンツ名プレフィックス | 次ホップ iwpid | 階層名 LPM（管理者設定） |
| **NMT** | 隣接 iwpid | 出力ポート | エコーパケットで 1 ホップ隣接を学習 |
| **NRS** | iwpid | IP アドレス | 外部サーバー（DNS 相当） |

---

## 4. Interest 処理フロー（メイン）

```mermaid
flowchart TD
    START([Interest 受信]) --> PIT_REC["PIT に受信ポートを記録"]
    PIT_REC --> LCST{"LCST 検索\n(コンテンツ名)"}

    LCST -->|"ヒット\n(on-path キャッシュ)"| DATA_SEND["Data 送信機構へ\n(§5)"]
    LCST -->|"ミス"| ECST{"ECST 検索\n(コンテンツ名 完全マッチ)"}

    ECST -->|"ヒット\n(off-path キャッシュ)"| GET_IWPID1["キャッシュ保有 iwpid 取得"]
    ECST -->|"ミス"| FIB{"FIB 検索\n(コンテンツ名 LPM)"}

    FIB -->|"ヒット"| GET_IWPID2["次ホップ iwpid 取得\n(Producer 方向)"]
    FIB -->|"ミス"| DROP([Drop / エラー])

    GET_IWPID1 --> INT_FWD["Interest 転送機構へ\n(§6)"]
    GET_IWPID2 --> INT_FWD

    style LCST fill:#d5f5e3,stroke:#27ae60
    style ECST fill:#d6eaf8,stroke:#2980b9
    style FIB fill:#fdebd0,stroke:#e67e22
    style DATA_SEND fill:#e8daef,stroke:#8e44ad
```

---

## 5. Data 送信・転送フロー

```mermaid
flowchart TD
    START([Data 送信開始]) --> SRC{"Data の発生元"}

    SRC -->|"LCST ヒット"| LOCAL["自ノード LCST から\nData を生成"]
    SRC -->|"Producer / 他 IWP から受信"| RECV["Data パケット受信"]

    LOCAL --> ENCAP["IP ヘッダでカプセル化\n(dst = consumer IP)"]
    RECV --> ENCAP

    ENCAP --> PIT{"PIT 検索\n(コンテンツ名)"}

    PIT -->|"ヒット"| PIT_FWD["PIT 記録ポートへ転送\n(逆方向)"]
    PIT -->|"ミス"| IP_FWD["通常 IP 転送\n(IP ルーティングテーブル参照)"]

    PIT_FWD --> NEXT{"次ホップは?"}
    NEXT -->|"IWP"| IWP_OUT["IWP が ICN 処理"]
    NEXT -->|"IP ルータ"| IP_ONLY["IP のみ転送\n(ICN 非認識)"]

    IP_FWD --> IP_ONLY
    IWP_OUT --> CONSUMER([Consumer へ到達])

    IP_ONLY -->|"IP ヘッダ維持"| CONSUMER

    style LOCAL fill:#d5f5e3,stroke:#27ae60
    style PIT fill:#d6eaf8,stroke:#2980b9
    style IP_FWD fill:#fdebd0,stroke:#e67e22
```

**過渡期の制約:** Data に consumer IP を指定するため、同一 Data を
複数 Consumer へ PIT マルチキャストできない（全 IWP 化後に解消）。

---

## 6. Interest 転送機構（NMT / NRS 分岐）

```mermaid
flowchart TD
    START([Interest 転送機構\n転送先 iwpid 確定済み]) --> NMT{"NMT 検索\n(iwpid → 出力ポート)"}

    NMT -->|"ヒット\n(隣接 IWP)"| ADJ["IP でカプセル化\n(consumer IP 保持)"]
    ADJ --> DIRECT["出力ポートへ直接転送\n(IP テーブルは参照しない)"]

    NMT -->|"ミス (null)\n(非隣接 IWP)"| NRS{"NRS 問い合わせ\n(iwpid → IP アドレス)"}
    NRS -->|"ヒット"| ENCAP["dst IP = 対象 IWP\nIP でカプセル化"]
    NRS -->|"ミス"| ERR([転送不可])

    ENCAP --> IP_ROUTE["通常 IP 転送\n(IP ルーティングテーブル参照)"]
    IP_ROUTE --> IP_HOP["IP ルータを経由可能\n(中身は ICN パケット)"]

    DIRECT --> NEXT_IWP([次 IWP / Producer])
    IP_HOP --> NEXT_IWP

    style NMT fill:#d6eaf8,stroke:#2980b9
    style NRS fill:#eafaf1,stroke:#27ae60
    style DIRECT fill:#e8f4fc,stroke:#2980b9
    style IP_ROUTE fill:#fdebd0,stroke:#e67e22
```

---

## 7. End-to-End シナリオ（off-path キャッシュ）

```mermaid
sequenceDiagram
    participant C as Consumer
    participant S1 as IWP s1
    participant S2 as IWP s2<br/>(ECST: コンテンツ@s3)
    participant S3 as IWP s3<br/>(LCST ヒット)
    participant P as Producer

    C->>S1: Interest (content=/a/b)
    Note over S1: PIT 記録, LCST ミス
    S1->>S2: Interest 転送 (FIB)
    Note over S2: PIT 記録, LCST ミス<br/>ECST ヒット → iwpid=s3
    S2->>S3: Interest 転送 (NMT/NRS)
    Note over S3: LCST ヒット
    S3-->>S2: Data (IP, dst=consumer)
    Note over S2: PIT 逆転送
    S2-->>S1: Data
    Note over S1: PIT 逆転送
    S1-->>C: Data
    Note over P: Producer 未到達
```

---

## 8. テーブル構築・更新フロー

```mermaid
flowchart TD
    subgraph lcst_build["LCST 構築"]
        D1[Data パケット通過] --> F1{キャッシュ提案\nflag = 1?}
        F1 -->|Yes| W1["LCST に登録\n(コンテンツ名 → データ)"]
        F1 -->|No| SKIP1[キャッシュしない]
    end

    subgraph ecst_build["ECST 構築"]
        T1[定期タイマー] --> N1["各 IWP が数ホップ先へ\nキャッシュ情報を通知\n(コンテンツ名 + 自 iwpid)"]
        N1 --> W2["近隣 IWP の ECST に記録"]
    end

    subgraph nmt_build["NMT 構築（隣接 IWP 学習）"]
        T2[定期タイマー] --> E1["エコーパケット送信\n(自 iwpid, 1 ホップ)"]
        E1 --> W3["受信 IWP が NMT に記録\n(隣接 iwpid → 受信ポート)"]
    end

    subgraph fib_build["FIB 構築"]
        A1[管理者 / 制御プレーン] --> W4["コンテンツ名プレフィックス\n→ 次ホップ iwpid"]
    end

    subgraph nrs_build["NRS 構築"]
        A2[外部 NRS サーバー] --> W5["iwpid → IP アドレス\n(DNS 相当)"]
    end
```

---

## 9. 移行ロードマップ

```mermaid
flowchart LR
    P1["Phase 1\n混在ネットワーク\n(本設計)"]
    P2["Phase 2\nIWP 増加\nECST 効果拡大"]
    P3["Phase 3\n全 IWP 化\nICN ネイティブ"]

    P1 -->|"IP カプセル化\nconsumer IP 指定"| P2
    P2 -->|"IP ルータ削減"| P3
    P3 --> MC["PIT ベース\n純粋マルチキャスト"]

    style P1 fill:#fdebd0,stroke:#e67e22
    style P2 fill:#d6eaf8,stroke:#2980b9
    style P3 fill:#d5f5e3,stroke:#27ae60
    style MC fill:#e8daef,stroke:#8e44ad
```

---

## 関連ファイル

| ファイル | 内容 |
|---------|------|
| `設計メモ.txt` | 設計の原文 |
| `generate_architecture_flowchart.py` | PNG 図の再生成スクリプト |
| `architecture_interest_flow.png` | Interest 処理フロー（PNG） |
| `architecture_interest_forward.png` | Interest 転送 NMT/NRS（PNG） |
| `architecture_packet_structure.png` | L1/L2/IP/ICN パケット構成図 |
| `architecture_packet_layers.png` | 各装置が参照するレイヤ |
| `generate_packet_structure.py` | パケット構成 PNG 再生成 |
| `chunk_table/` | Phase 1 実装（L2 ICN + on-path キャッシュ） |
| `mcd_cache/` | IP オーバーレイ試作 |
| `METHODOLOGY.md` | 性能評価手法 |
