# altanative-teket

teket代替の1団体専用チケット販売システム（東京芸術劇場コンサートホール・1公演・指定席）。

## 構成
- `frontend/` Vite + React + TypeScript。`VITE_API_MODE=mock|live` でAPIクライアント切替（`src/api/`）
- `frontend/src/data/seats.json` 座席データ。`tools/seatmap/extract.py` で座席表PDFから生成（PDFはコミットしない）
- `backend/` サーバー側（Python）。料金計算は `backend/app/pricing.py` と `frontend/src/lib/seats.ts` で同じ規則を保つ
- `.github/workflows/ci.yml` PR時に front/back のチェックを実行

## コマンド
- Frontend: `cd frontend && npm ci && npm run lint && npm run build`
- Backend/tools（uv）: `uv sync && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q`
- 座席データ再生成: `uv run python tools/seatmap/extract.py <座席表.pdf> frontend/src/data/seats.json`

## ルール
- Python は ruff（lint/format）と ty（型）を通すこと。フロントは oxlint と `tsc -b` を通すこと
- 画面変更時はモックモードで Playwright のスクショを撮ってユーザーに見せる（GitHub Pagesはユーザーが必要時に作成）
- 秘密情報（Stripeキー等）はコード・Terraformの値に含めない

## PR作成前のレビュー（必須）
PRを作成する前に、必ずサブエージェント（Agentツール）にコードレビューを依頼すること。
1. 上記の CI と同じチェックをローカルで全て通す
2. サブエージェントに `git diff main...HEAD` を対象として、正しさ（在庫・決済・冪等性・競合）、セキュリティ（認証・トークン・秘密情報）、料金計算の front/back 一致を重点にレビューさせる
3. 指摘を修正するか、修正しない理由をPR本文に記載する
4. その後にPRを作成する
