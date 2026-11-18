# altanative-teket

teket 代替の 1 団体専用チケット販売システム（東京芸術劇場コンサートホール・1公演・指定席）。

- 仕様: `plans/spec-v0.1.md`（`plans/decisions.md` が優先）
- インフラ構築・運用の詳細手順: [`infra/README.md`](infra/README.md)

## 環境一覧

| 環境 | 用途 | フロント | API | データ・決済 | 起動方法 |
|---|---|---|---|---|---|
| ローカル（モック） | 画面開発・スクショ | Vite dev server | ブラウザ内モック | ダミーデータ（AWS/Stripe 不要） | `npm run dev` |
| ローカル（live） | API 結合確認 | Vite dev server（`/api` を :8000 に中継） | uvicorn（FastAPI） | DynamoDB（実 or Local）、Stripe テストキー | 下記「ローカル（live）」 |
| GitHub Pages | 見た目確認用プレビュー | Pages（モックビルド） | ブラウザ内モック | ダミーデータ | main マージで `pages.yml`（frontend 変更時） |
| 本番（production） | 実販売 | S3 + CloudFront | API Gateway → Lambda（Mangum） | DynamoDB、SES、Stripe 本番、SSM | main マージで `deploy.yml` |

ステージング環境はない。結合確認はローカル（live）＋ Stripe テストモードで行う。

## 前提ツール

| ツール | バージョン | 用途 |
|---|---|---|
| Node.js | 22 | frontend |
| uv | 最新 | backend / tools（Python 3.13 は uv が用意） |
| Terraform | 1.17.2 | infra |
| AWS CLI | v2 | SSM 登録・データ投入（本番のみ） |
| Stripe CLI | 任意 | ローカルで Webhook を受ける場合 |

## ローカル（モック）

```sh
cd frontend
npm ci
npm run dev        # VITE_API_MODE 未指定 = mock
```

## ローカル（live）

```sh
uv sync
TABLE_NAME=teket-alt EVENT_ID=evt_2027 SITE_URL=http://localhost:5173 \
STRIPE_SECRET_KEY=sk_test_... STRIPE_WEBHOOK_SECRET=whsec_... \
STAFF_KEY=dev JWT_SECRET=dev ADMIN_PASSWORD_HASH='...' \
  uv run uvicorn app.main:app --app-dir backend --port 8000

stripe listen --forward-to localhost:8000/api/stripe/webhook   # whsec_ を STRIPE_WEBHOOK_SECRET に
cd frontend && VITE_API_MODE=live npm run dev
```

- DynamoDB Local を使う場合は `AWS_ENDPOINT_URL_DYNAMODB=http://localhost:8001` のように uvicorn と別ポートで指定
- `ADMIN_PASSWORD_HASH` は `PYTHONPATH=backend uv run python -m app.cli hash-password` で生成
- 公演・座席データ投入は `infra/README.md` の「データ投入」と同じ CLI（`seed-event` / `seed-seats`）

## 環境変数

### フロントエンド（ビルド時）

| 変数 | 既定 | 説明 |
|---|---|---|
| `VITE_API_MODE` | `mock` | `mock` / `live`。本番ビルドは `live` |
| `VITE_API_BASE_URL` | 空（同一オリジン） | API の基点 URL |
| `VITE_BASE` | `/` | 配信パス。Pages では `/<repo>/` |
| `VITE_SITE_NAME` | `チケット` | サイト名 |
| `VITE_SELLER_NAME` | `（団体名）` | 特商法表記等の販売者名 |

### バックエンド

| 変数 | 既定 | 説明 |
|---|---|---|
| `TABLE_NAME` | `teket-alt` | DynamoDB テーブル名 |
| `EVENT_ID` | `evt_2027` | 公演 ID |
| `SITE_URL` | `http://localhost:5173` | 決済後の戻り先・メール内リンク |
| `MAIL_FROM` | `tickets@example.com` | SES 送信元 |
| `SSM_PREFIX` | 未設定 | 設定時は秘密情報を SSM から読む（本番は `/teket-alt`） |

本番では Terraform（`infra/lambda.tf`）が Lambda に設定する。

### 秘密情報

| 名前 | 内容 |
|---|---|
| `stripe_secret_key` | Stripe シークレットキー |
| `stripe_webhook_secret` | Stripe Webhook 署名シークレット |
| `staff_key` | 受付画面 URL のキー（`旧,新` でローテーション可） |
| `jwt_secret` | 管理画面セッション署名 |
| `admin_password_hash` | 管理者パスワードのハッシュ |

- 本番: SSM パラメータストア `<SSM_PREFIX>/<名前>`（SecureString）。60秒キャッシュ
- ローカル: `SSM_PREFIX` 未設定時、同名の大文字環境変数（例 `STRIPE_SECRET_KEY`）
- コード・Terraform の値・リポジトリに含めない

## CI/CD

| ワークフロー | トリガー | 内容 |
|---|---|---|
| `ci.yml` | PR / main push | frontend（oxlint, `tsc -b`, build）、backend（ruff, ty, pytest）、terraform（fmt, validate） |
| `deploy.yml` | main push / 手動 | backend チェック → Lambda zip → frontend live ビルド → `terraform apply` → S3 アップロード・CloudFront 無効化 |
| `pages.yml` | main push（frontend 変更） / 手動 | モックビルドを GitHub Pages に配信 |

### GitHub 側の設定（本番デプロイ用）

- Environment `production`（Deployment branches を `main` のみに制限）
- リポジトリ変数: `AWS_DEPLOY_ROLE_ARN`, `TF_STATE_BUCKET`（未設定ならデプロイはスキップ）、任意で `AWS_REGION`（既定 `ap-northeast-1`）, `EVENT_ID`, `DOMAIN_NAME`, `ROUTE53_ZONE_NAME`, `MAIL_FROM`, `ALARM_EMAIL`
- AWS 認証は OIDC（`infra/bootstrap` で作成するロール）。長期キーは使わない
- Pages を使う場合は Settings → Pages → Source を「GitHub Actions」に

## ローカルでのチェック（CI と同じ）

```sh
cd frontend && npm ci && npm run lint && npm run build
uv sync && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
terraform fmt -check -recursive infra && terraform -chdir=infra init -backend=false && terraform -chdir=infra validate
```

## ディレクトリ

```
frontend/   Vite + React + TypeScript（src/api/ で mock/live 切替、src/data/seats.json 座席データ）
backend/    FastAPI + Mangum。app/service.py 業務ロジック、app/db.py キー設計、app/cli.py 運用 CLI
infra/      Terraform（bootstrap/ は初回のみ手動）
tools/      座席データ生成（seatmap/extract.py）
plans/      仕様・合意事項
assets/     座席表 PDF
```
