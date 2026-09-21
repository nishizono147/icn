#!/bin/bash
# P4 研究・演習環境を起動する。
#
# このリポジトリのルートを /work にマウントし、p4-icn-router をカレントにする。
# 演習 (exercises/) も同じマウント内にあるので、そのまま行き来できる。
#
# --privileged が必要な理由:
#   Mininet はネットワーク名前空間と veth ペアを生成するため、通常の
#   コンテナ権限では動かない。ホストのカーネル機能をほぼ全面開放するので、
#   研究・学習用途に限定すること。
set -euo pipefail

IMAGE="p4dev:24.04"
REPO="$(cd "$(dirname "$0")" && pwd)"

if ! docker image inspect "${IMAGE}" > /dev/null 2>&1; then
    echo "イメージ ${IMAGE} がありません。次で構築してください:" >&2
    echo "  docker build -t ${IMAGE} ${REPO}" >&2
    exit 1
fi

exec docker run -it --rm \
    --privileged \
    --name p4 \
    -v "${REPO}:/work" \
    -w /work/p4-icn-router \
    "${IMAGE}" \
    /bin/bash
