#!/usr/bin/env bash
# Lambda(arm64, Python 3.13) 用 zip を backend/dist/lambda.zip に作る
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=backend/dist
rm -rf "$OUT/pkg" "$OUT/lambda.zip"
mkdir -p "$OUT/pkg"
uv export --frozen --no-dev --no-default-groups --no-hashes --no-emit-project -o "$OUT/requirements.txt" >/dev/null
uv pip install --quiet --target "$OUT/pkg" --python-platform aarch64-manylinux2014 --python-version 3.13 \
  --only-binary :all: -r "$OUT/requirements.txt"
cp -r backend/app "$OUT/pkg/app"
cp frontend/src/data/seats.json "$OUT/pkg/app/seats.json"
find "$OUT/pkg" -name "__pycache__" -type d -prune -exec rm -rf {} +
# 再現性のため更新日時を固定（Terraform の source_code_hash を安定させる）
find "$OUT/pkg" -exec touch -t 202001010000 {} +
(cd "$OUT/pkg" && find . -type f | LC_ALL=C sort | zip -qX -@ ../lambda.zip)
ls -lh "$OUT/lambda.zip"
