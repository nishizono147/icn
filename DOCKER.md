# Docker 実行環境

このリポジトリ（ICN 研究と p4lang/tutorials の演習）を動かすためのコンテナ環境。

## 使い方

```
./run.sh
```

リポジトリのルートが `/work` にマウントされ、`/work/p4-icn-router` がカレントになる。

```
/work/p4-icn-router/    ICN 研究の本体
/work/exercises/        p4lang/tutorials の演習 13 個
/work/utils/            Mininet ハーネス（各 Makefile が include する）
```

実験の実行例:

```
cd pit_table
make run          # ビルド → Mininet 起動 → テーブル投入
mininet> pingall
mininet> exit
make clean        # 後片付け（重要。下記参照）
```

終了はコンテナのシェルで `exit`。`--rm` 付きなのでコンテナは自動削除される。

## 構成

| 要素 | バージョン |
|---|---|
| ベースOS（コンテナ内） | Ubuntu 24.04 |
| p4c | 1.2.5.17 (SHA: 66edefceaa) |
| BMv2 (simple_switch) | 1.15.1 |
| Mininet | 2.3.1b4 |
| PTF | 0.12.3 |
| behavioral-model commit | f97d375d (2026-05-07 に固定) |

このリポジトリの fork 元は 2026-05-01 時点の p4lang/tutorials であり、
固定した behavioral-model (2026-05-07) とほぼ同時期のため、想定している
ツールチェーンの版が一致している。`p4-icn-router` 配下の
`pit_table` / `chunk_pull` / `chunk_table` はいずれもコンパイル確認済み。

## 注意点

- **コンテナ内で作ったファイルはホスト側で root 所有になる。** コンテナは
  root で動く（Mininet に必要）ため、`build/` `logs/` `pcaps/` をホストから
  削除できなくなる。ホスト側で `rm` せず、**コンテナ内で `make clean`** を
  使うこと。git は `build*/` 等を無視するので履歴は汚れない。
- `mn` と `ptf` は `/opt/p4dev/p4dev-python-venv/bin` にある。イメージの
  `ENV` に PATH を焼き込んであるので、対話・非対話どちらでも意識不要。
  （`.bashrc` だけに書くと `docker exec` で見つからず落ちる。構築時に実際に踏んだ）
- `--privileged` が必須（Mininet が netns と veth を作るため）。
- ヘッドレスなので `xterm h1` は使えない。`mininet> h1 <コマンド>` で代用する。

## 構築時に踏んだ罠

Dockerfile のコメントに詳細を記載。要点は3つ。

1. **ホストの Ubuntu 26.04 はインストーラ非対応**（22.04 / 24.04 / 25.10 のみ）。
   コンテナ内だけ 24.04 に固定して回避している。
2. **`install-p4dev-v10.sh` は現状動かない** — 当てるパッチの1つ
   (`behavioral-model-support-venv-thrift-0.22.0.patch`) が upstream のどの版にも
   適用できない。v9 + behavioral-model を `f97d375d` に固定して回避
3. **インストーラの出力をパイプで受けてはいけない** — 常駐する
   `keep-sudo-credentials-fresh.sh` がパイプを掴んだままになりビルドが
   終わらない。ログはファイルへ

また、インストーラの再開判定は「ディレクトリの存在」だけを見るため、
**失敗したまま再実行すると壊れた中間状態を「導入済み」と誤認して飛ばす**。
再試行前に該当ディレクトリを削除すること。

## イメージの再構築

```
docker build -t p4dev:24.04 .
```

ソースから全てビルドするため 1〜2 時間かかる。
