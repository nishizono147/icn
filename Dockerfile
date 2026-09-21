# P4 開発環境 — p4c / BMv2 / PI / Mininet / PTF
#
# ============================================================================
# なぜコンテナを使うのか
# ============================================================================
# ホストは Ubuntu 26.04 だが、p4-guide のインストーラが対応するのは
#   ID ubuntu, VERSION_ID in 22.04 24.04 25.10
# のみで、26.04 は対象外。コンテナ内のユーザ空間だけ 24.04 に固定して回避する。
# これが「あると便利」ではなく「ほぼ必須」である理由。
#
# ============================================================================
# なぜ v10 ではなく v9 なのか / なぜ commit を固定するのか
# ============================================================================
# install-p4dev-v10.sh は behavioral-model へ2つのパッチを当てるが、そのうち
#   behavioral-model-support-venv-thrift-0.22.0.patch
# が upstream のどの版にも適用できない（2026-09 時点で9つの commit を検証済み）。
# v10 は現状どう頑張っても通らない。
#
# v9 のパッチ構成（fedora / venv-2026-apr / install-nanomsg-1.2.2）なら整合し、
# behavioral-model の f97d375d (2026-05-07) に対して3つとも適用できる。
# f97d375d は upstream が boost::filesystem を std::filesystem へ移行し、
# install_deps.sh のパッケージ一覧が変わる直前の版。
#
# P4 のツールチェーンは p4c / BMv2 / PI / protobuf / grpc のバージョン整合が
# シビアで、噛み合わないとビルドが通っても実行時に壊れる。学習環境としては
# 最新を追うより「動く既知の組み合わせ」を固定するのが正解。
# ============================================================================

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Tokyo

# インストーラが暗黙に前提とするツール群。
# 公式ドキュメントに記載がなく、通常の Ubuntu 環境に存在することが前提になっている。
#   patch       : behavioral-model へのパッチ適用。無いと exit 127 で即死
#   python3-dev : netifaces が C 拡張なので Python.h が必要
#   bc          : スクリプト内の算術で使用
#   wget/xz-utils/bzip2 : 各所のダウンロードと展開
RUN apt-get update && apt-get install -y --no-install-recommends \
        sudo git curl wget ca-certificates tzdata lsb-release \
        patch xz-utils bzip2 bc \
        python3 python3-pip python3-dev \
        libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 演習の実行に必要なネットワークツール。
# ping が無いと Mininet の pingall が "command not found" で全滅する。
# tcpdump は pcap 確認、iperf は qos / load_balance の演習で使用。
RUN apt-get update && apt-get install -y --no-install-recommends \
        iputils-ping iproute2 net-tools tcpdump iperf iperf3 \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/jafingerhut/p4-guide.git /opt/p4-guide

WORKDIR /opt/p4dev

# 出力は必ずファイルへ落とすこと。パイプ（| tail 等）で受けてはいけない。
# インストーラは keep-sudo-credentials-fresh.sh を常駐させる設計で、これが
# パイプを掴んだまま離さないため、本体が終了しても EOF が来ずビルドが
# 永久に終わらなくなる。しかも失敗原因がバッファごと失われる。
RUN INSTALL_BEHAVIORAL_MODEL_SOURCE_VERSION=f97d375d \
    /opt/p4-guide/bin/install-p4dev-v9.sh > /opt/p4dev/install.log 2>&1 \
    || (tail -100 /opt/p4dev/install.log; exit 1)

# mn と ptf は /opt/p4dev/p4dev-python-venv/bin に入るため素の PATH では見えない。
# .bashrc への追記だけだと対話シェルでしか効かず、docker exec や
# `docker run ... bash -c` のような非対話実行で mn が見つからず落ちる。
# 実際にこれを踏んだので、ENV としてイメージに焼き込む。
RUN echo 'source /opt/p4dev/p4setup.bash' >> /root/.bashrc
ENV VIRTUAL_ENV=/opt/p4dev/p4dev-python-venv
ENV PATH=/opt/p4dev/p4dev-python-venv/bin:/opt/p4-guide/bin:/opt/p4dev/behavioral-model/tools:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin
ENV P4_EXTRA_SUDO_OPTS=PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

WORKDIR /work
CMD ["/bin/bash"]
