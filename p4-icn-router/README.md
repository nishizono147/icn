# p4-icn-router

P4（BMv2）で ICN ルータ（IWP）を実装し、キャッシュ配置の工夫を評価する研究のリポジトリ。

- **目的**: キャッシュ配置を工夫した ICN を普及させる
- **アプローチ**: IWP を専用ハードウェアではなく P4 でソフトウェアとして実装し、導入の壁を下げる。
  独自プロトコルを扱え、キャッシュ配置の方式も柔軟に変えられる
- **今できていること**: コンテンツ ID + MCD による on-path キャッシュ（経路上に動的に配置）と、
  複数パケット（チャンク）による大きいコンテンツの転送の基盤

## ディレクトリ

| ディレクトリ | 内容 | 状態 |
|---|---|---|
| `pit_table/` | PIT + MCD キャッシュ。1 コンテンツ = 1 Data（256 B） | 完了 |
| `mcd_cache/` | MCD キャッシュの実装（今の研究の流れとは別の目的で作成） | 完了 |
| `ip_baseline/` | 比較用の IPv4 転送 + UDP 要求／応答（キャッシュなし） | 完了 |
| `chunk_table/` | 複数チャンク + MCD。Interest 1 本でスイッチが全チャンクを返す（clone + recirculate） | 比較用として固定 |
| `chunk_pull/` | 複数チャンク + MCD。チャンクごとに Interest を送る | **今後の土台** |

トポロジはどれも `h1（Consumer）─ s1 ─ s2 ─ s3 ─ h2（Producer）`。
MCD では要求のたびにキャッシュが Consumer 側へ 1 ホップずつ移動する
（1 回目 h2 から返す → 2 回目 s3 → 3 回目 s2 → 4 回目以降 s1）。

## chunk_table と chunk_pull の比較

| | chunk_table | chunk_pull |
|---|---|---|
| Interest | 1 本 | chunk 0 を送り、チャンク数を知ったら残りをまとめて送る |
| 往復の回数 | 1 回 | 2 回 |
| スイッチの機能 | `clone` + `recirculate`（BMv2 依存） | 通常の転送と register のみ |
| 失われたチャンク | 個別に要求し直せない | そのチャンクだけ要求し直せる |

計測結果（取得時間 ms、各 20 セッションの平均。`results/compare_chunk_methods.png`）:

| 返す場所 | 4 チャンク table / pull | 10 チャンク table / pull |
|---|---|---|
| h2（1 回目） | **5.01** / 8.22 | **7.11** / 12.94 |
| s3（2 回目） | **5.37** / 7.27 | **9.36** / 11.70 |
| s2（3 回目） | **4.42** / 5.09 | **8.17** / 9.12 |
| s1（4 回目以降） | 2.82〜2.97 / **2.63〜2.70** | 6.5〜6.8 / **5.7〜5.9** |

キャッシュが遠いと chunk_table、近いと chunk_pull が速く、チャンク数が増えると差が広がる。
chunk_table はキャッシュから返すとき 1 チャンクごとにスイッチ内で一周（recirculate）させるため、
近くから返す場合はそのコストが目立つ。MCD ではよく要求されるコンテンツが Consumer の近くに来るので、
今後は chunk_pull を土台にする。

## 実験の回し方

Mininet が必要なので、Docker のコンテナ内で実行する（詳細は `../DOCKER.md`）。

```bash
../run.sh    # コンテナに入る。カレントは /work/p4-icn-router

# chunk_table と chunk_pull を交互に計測（10 チャンク、20 セッション）
python3 run_compare_chunk_methods.py -s 20 --content-id 6 \
    --systems table,pull-burst --out-prefix results/compare_chunk_methods_c10
```

- 1 セッション = Mininet 起動 → Producer 起動 → 同じコンテンツを 10 回連続で要求 → Mininet 停止。
  方式ごとに 1 セッションずつ交互に回し、セッションごとに先に回す方式を入れ替える
- `--systems`: `table`、`pull-burst`（残りをまとめて送る）、`pull-sequential`（1 つずつ送る）
- `--content-id`: `4` = `image4.png`（4 チャンク）、`6` = `content10.bin`（10 チャンク）。
  スイッチの上限は 1 コンテンツ 10 チャンク
- 各試行で、全チャンクが届いたか、返す場所が MCD の想定どおりか、受け取った内容が元のファイルと
  一致するかを自動で確認する

グラフ（matplotlib と日本語フォントが必要。コンテナには入っていないので、使い捨てのコンテナで入れて実行する）:

```bash
python3 -m pip install matplotlib matplotlib-fontja
python3 plot_compare_chunk_methods.py \
    --panel "4 チャンク（1 KB）:results/compare_chunk_methods_raw.csv" \
    --panel "10 チャンク（2.5 KB）:results/compare_chunk_methods_c10_raw.csv" \
    --out results/compare_chunk_methods.png
```

### 取得時間の測り方（`consumer_bench.py`）

両方式で同じ Consumer を使い、違いは Interest の送り方だけにしている。

- Data は raw ソケット（AF_PACKET）で直接受け取り、Interest は事前に組み立てたバイト列を送る
- h1 で tcpdump（`--immediate-mode`）を回し、取得時間は試行がすべて終わった後に pcap の時刻から計算する
- 取得時間 = その試行の最初の Interest が h1 から出た時刻 → 全チャンクがそろった時刻

## 主なファイル

| ファイル | 内容 |
|---|---|
| `consumer_bench.py` | 共通の Consumer（`--mode table` / `--mode pull --pull-strategy burst\|sequential`） |
| `run_compare_chunk_methods.py` | 方式を交互に回して計測し、CSV に出力する |
| `plot_compare_chunk_methods.py` | 上の CSV からグラフを作る |
| `results/compare_chunk_methods_raw.csv` / `_summary.csv` | 4 チャンクの結果（3 方式） |
| `results/compare_chunk_methods_c10_raw.csv` / `_summary.csv` | 10 チャンクの結果 |
| `results/compare_chunk_methods_step1_*` / `_step2_*` | chunk_pull の PIT をチャンクごとに分ける前と後の確認 |
| `results/compare_chunk_methods.png` | 4 チャンクと 10 チャンクの比較グラフ |
| `METHODOLOGY.md` | ICN（pit_table）と IP の比較実験の手法 |
| `設計メモ.txt` | IP 上で動く ICN の設計（FIB / LCST / ECST / PIT / NMT / NRS） |
| `chunk_table/CHUNK_CACHE_DESIGN.md` | chunk_table のスイッチの設計 |
| `chunk_table/RESEARCH_POSITIONING.txt` | 先行研究（port 511 版）との関係 |

### 前の計測（使わない）

次のスクリプトと結果は、今の計測方法に置き換えたもの。比較には使わない。

- `chunk_table/benchmark_icn.py`、`chunk_pull/benchmark_icn.py`: 前の Consumer。
  chunk_pull 側は録画ファイルに Data が書かれるまで待ってから次の Interest を送るため、
  tcpdump のバッファ（最大約 1 秒）の分だけチャンクごとに待たされ、取得時間が約 2.7 秒になっていた
- `run_compare_chunk_table_pull_graph.py`: 数値をコードに直接書いてグラフにしている
- `results/compare_chunk_ip_means.csv`、`compare_chunk_table_pull.*`: 生成したスクリプトや手順がわからない
- `results/compare_chunk_ip.*`: 6 セッションのみで、セッションごとのばらつきが大きい（VirtualBox 環境）

## 今後の予定

詳細は [ROADMAP.md](ROADMAP.md)。

1. コンテンツ名（各階層をハッシュで固定長にして並べる。例: 32 bit × 4 階層 = 128 bit）
2. FIB（名前の最長プレフィックス一致 → 次の IWP）と NMT（IWP → 出力ポート）。
   今の Interest の転送は送信元 MAC アドレスで経路を決め打ちしている
3. off-path キャッシング（ECST と、キャッシュの位置の通知）
4. IP 上での動作（途中に通常の IP ルータがあっても通信できる）

2〜3 の間に、複数の Consumer に対応した PIT、キャッシュの置き換え、コンテンツ数とチャンク数の上限の見直しを入れる。
