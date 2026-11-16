# インフラ・運用手順

構成: CloudFront（S3 の静的サイト + `/api/*` → API Gateway HTTP API → Lambda(FastAPI)）、DynamoDB、SES、EventBridge（5分ごとの定期回収）。

```
infra/
├── bootstrap/   # 初回のみ手動 apply: state バケット、GitHub Actions 用 OIDC ロール
└── *.tf         # 本体。main へのマージで GitHub Actions(deploy.yml) が apply
```

## 初回セットアップ

1. **bootstrap**（管理者権限で手動。state はローカルに残るので安全な場所で保管）
   ```sh
   cd infra/bootstrap && terraform init && terraform apply
   ```
2. **GitHub の設定**
   - Environment `production` を作成（デプロイロールはこの environment からのみ引き受け可能）
     - **Deployment branches and tags を `main` のみに制限する**（必須。しないと他ブランチから本番ロールを使える）
     - 必要なら Required reviewers も設定
   - リポジトリ変数（Settings → Variables）
     | 変数 | 値 |
     |---|---|
     | `AWS_DEPLOY_ROLE_ARN` | bootstrap の `deploy_role_arn` |
     | `TF_STATE_BUCKET` | bootstrap の `state_bucket` |
     | `DOMAIN_NAME` | 例 `tickets.example.jp`（未定なら空。CloudFront の既定ドメインで動く） |
     | `ROUTE53_ZONE_NAME` | ホストゾーンが `DOMAIN_NAME` と異なる場合のみ（例 `example.jp`） |
     | `MAIL_FROM` | ドメインなしの場合は必須（SES でそのアドレスを認証する） |
     | `ALARM_EMAIL` | エラー通知先（任意） |
   - 2つの変数が揃うまで deploy ワークフローはスキップされる
3. **秘密情報を SSM に登録**（SecureString。Terraform は値を扱わない）
   ```sh
   P=/teket-alt
   aws ssm put-parameter --type SecureString --name $P/stripe_secret_key     --value 'sk_live_...'
   aws ssm put-parameter --type SecureString --name $P/stripe_webhook_secret --value 'whsec_...'
   aws ssm put-parameter --type SecureString --name $P/staff_key             --value "$(openssl rand -base64 24 | tr '+/' '-_' | tr -d =)"
   aws ssm put-parameter --type SecureString --name $P/jwt_secret            --value "$(openssl rand -base64 48)"
   aws ssm put-parameter --type SecureString --name $P/admin_password_hash   --value "$(PYTHONPATH=backend uv run python -m app.cli hash-password)"
   ```
4. **main にマージ**して deploy を実行 → 出力の `site_url` / `stripe_webhook_url` を確認
5. **データ投入**（`TABLE_NAME=teket-alt EVENT_ID=evt_2027 PYTHONPATH=backend` を付けて実行）
   ```sh
   uv run python -m app.cli seed-event backend/event.json   # 公演情報。published=true で販売開始可能に
   uv run python -m app.cli seed-seats                      # 2,003席を AVAILABLE で作成（既存席は変更しない）
   uv run python -m app.cli import-coupons coupons.txt      # 1行1コード。リポジトリには置かない
   ```
   クーポンコードは推測されないよう8文字以上のランダムな文字列にする。
6. **Stripe**: Webhook エンドポイントに `stripe_webhook_url` を登録し、イベント `checkout.session.completed` と `checkout.session.expired` を選ぶ
7. **申請**（新規アカウント）: SES のサンドボックス解除、Lambda 同時実行数の上限緩和、Stripe の本番審査

## 運用

- **受付URL**: `https://<site>/staff#key=<staff_key>`。ローテーションは SSM の `staff_key` を `旧キー,新キー` にして新URLを配布 → 全員が切り替えたら `新キー` だけにする（反映は約1分）
- **日時**はタイムゾーン付きで書く（`+09:00` でも可。保存時に UTC に正規化）
- **価格・公演情報の変更**: `backend/event.json` を編集して `seed-event` を再実行（約30秒で反映。確定済みの注文の金額は変わらない）
- **定期回収**（5分ごと）: 期限切れの決済待ち注文を Stripe に確認して確定または解放し、送信に失敗したメールを再送する
- **返金**: Stripe ダッシュボードから手動。CloudWatch アラームの `PAID_AFTER_RELEASE`（座席解放後に決済が完了した注文。通常は起きない）が出たら、その注文を返金する（管理画面の一覧にも EXPIRED のまま表示される）
- **メール送信失敗**: 定期回収で約30分再送し、それでも失敗したら `EMAIL_GAVE_UP` のアラームを出して再送をやめる。原因（SES・Stripe の障害など）を確認して管理画面から再送する。宛先は Stripe ダッシュボードの決済で確認できる（0円注文は Stripe を通らないため、再送しない場合は下記 `purge-emails --all` で消す）
- **メールアドレスの削除**: DB には送信待ちの0円注文のメールしか残らない。メールを保存していた頃の注文が残っている場合はデプロイ後に一度、公演後にも `--all` 付きで実行する（PITR のバックアップには最大35日残る）
  ```sh
  uv run python -m app.cli purge-emails         # 送信済み・期限切れの注文からメールを削除
  uv run python -m app.cli purge-emails --all   # 送信待ちも含めて全て削除
  ```
- **ログ**: CloudWatch Logs `/aws/lambda/teket-alt-api`（90日保持）
- DynamoDB はポイントインタイムリカバリと削除保護を有効にしている

## ローカル開発

```sh
# DynamoDB Local 等を使う場合は AWS_ENDPOINT_URL_DYNAMODB=http://localhost:8000 なども指定可
TABLE_NAME=... STRIPE_SECRET_KEY=sk_test_... STRIPE_WEBHOOK_SECRET=whsec_... STAFF_KEY=dev JWT_SECRET=dev \
ADMIN_PASSWORD_HASH='...' SITE_URL=http://localhost:5173 \
  uv run uvicorn app.main:app --app-dir backend --port 8000
stripe listen --forward-to localhost:8000/api/stripe/webhook
cd frontend && VITE_API_MODE=live npm run dev   # /api は :8000 に中継される
```
`SSM_PREFIX` を設定しない場合、秘密情報は同名の環境変数（大文字）から読む。
