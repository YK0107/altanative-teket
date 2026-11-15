# チケット販売システム 仕様書（v0.1）

teket代替として、1団体専用で運用する最小構成のチケット販売システム。

---

## 1. 前提・スコープ

| 項目 | 方針 |
|---|---|
| 利用者 | 1団体のみ（マルチテナント不要） |
| 決済 | Stripe Checkout（カードのみ）。カード情報は自前で保持しない |
| キャンセル・返金 | **原則不可**（規約・特商法表記に明記）。イベント中止時のみStripeダッシュボードから手動返金 |
| 領収書 | 発行しない（必要ならStripe自動レシートメールをONにするだけ） |
| 当日受付 | オンライン前提。オフライン対応はしない |
| コンビニ払い等 | 対象外 |

## 2. 技術スタック

| レイヤ | 技術 |
|---|---|
| フロント | Vite + React + TypeScript |
| API | FastAPI（Python）+ Mangum |
| 実行環境 | AWS Lambda（1関数に集約）+ API Gateway（HTTP API） |
| DB | DynamoDB（シングルテーブル） |
| メール | Amazon SES（独自ドメイン、DKIM/SPF設定） |
| 静的ホスティング | S3 + CloudFront（本番）/ GitHub Pages（dev） |
| IaC | AWS CDK（Python） |
| CI/CD | GitHub Actions |
| 型共有 | FastAPIのOpenAPI → `openapi-typescript` でTS型生成 |

## 3. 環境

| 環境 | フロント | API | 決済 | 用途 |
|---|---|---|---|---|
| dev | GitHub Pages | なし（フロント内モック） | なし | 見た目確認 |
| local | `vite dev` | `uvicorn` | Stripeテストモード + `stripe listen` | 決済フロー含む動作確認 |
| prod | S3 + CloudFront | Lambda | Stripe本番 | 本番運用 |

- 切替は `VITE_API_MODE=mock | live` と `VITE_API_BASE_URL`
- APIクライアント層を1箇所に集約し、mock時はダミーJSON・購入ボタンで即完了画面へ遷移
- GitHub Pages：`base: '/<repo>/'` 設定、SPAルーティングは `404.html` コピー or HashRouter、`noindex` 付与

## 4. 機能一覧

### 4.1 購入者
- イベント一覧・詳細表示（日時・会場・価格・残数）
- 枚数選択 → メールアドレス・氏名入力 → Stripe Checkoutへ遷移
- 決済完了画面
- 電子チケットメール受信（QRコード + チケットURL）
- チケット表示ページ（`/t/{token}`：QR表示、使用済み表示）

### 4.2 受付スタッフ
- QR読取ページ（スマホブラウザ、カメラ使用）
- 読取結果表示：OK / 使用済み / 無効
- 入場処理（使用済みフラグを立てる）

### 4.3 管理者
- イベント作成・編集（名称、日時、会場、価格、定員、販売期間、公開/非公開）
- 販売状況（販売数・残数・売上）
- 参加者一覧・CSV出力
- 返金はStripeダッシュボードで実施（システム側は対象外、必要なら手動でステータス変更）

## 5. 画面一覧

| パス | 画面 | 認証 |
|---|---|---|
| `/` | イベント一覧 | なし |
| `/events/{id}` | イベント詳細・購入フォーム | なし |
| `/purchase/success` | 決済完了 | なし |
| `/purchase/cancel` | 決済中断 | なし |
| `/t/{token}` | 電子チケット | トークン |
| `/staff/scan` | QR受付 | スタッフ |
| `/admin` | 管理トップ・イベント管理 | 管理者 |
| `/admin/events/{id}` | 販売状況・参加者一覧 | 管理者 |
| `/legal/tokushoho` | 特商法表記 | なし |
| `/legal/terms` | 利用規約 | なし |
| `/legal/privacy` | プライバシーポリシー | なし |

## 6. API

| メソッド | パス | 概要 | 認証 |
|---|---|---|---|
| GET | `/api/events` | 公開イベント一覧 | なし |
| GET | `/api/events/{id}` | イベント詳細（残数含む） | なし |
| POST | `/api/checkout` | 在庫予約 + Stripe Checkout Session作成、URL返却 | なし |
| POST | `/api/stripe/webhook` | Stripe Webhook受信 | Stripe署名 |
| GET | `/api/tickets/{token}` | チケット情報取得 | トークン |
| POST | `/api/staff/checkin` | QRトークンで入場処理 | スタッフ |
| GET/POST/PUT | `/api/admin/events[...]` | イベントCRUD | 管理者 |
| GET | `/api/admin/events/{id}/attendees` | 参加者一覧（`?format=csv`） | 管理者 |

### POST `/api/checkout`
```json
// request
{ "event_id": "evt_xxx", "quantity": 2, "name": "山田太郎", "email": "a@example.com" }
// response
{ "checkout_url": "https://checkout.stripe.com/..." }
```

## 7. データモデル（DynamoDB シングルテーブル）

| エンティティ | PK | SK | 主な属性 |
|---|---|---|---|
| Event | `EVENT#{event_id}` | `META` | name, starts_at, venue, price, capacity, **remaining**, sales_start, sales_end, published |
| Order | `ORDER#{order_id}` | `META` | event_id, name, email, quantity, amount, status, stripe_session_id, expires_at, created_at |
| Ticket | `TICKET#{token}` | `META` | ticket_id, order_id, event_id, used_at |

- GSI1：`GSI1PK=EVENT#{event_id}` / `GSI1SK=ORDER#{created_at}` … イベント別注文一覧（参加者一覧・CSV用）
- Order.status：`PENDING` → `PAID` / `EXPIRED`（手動で `REFUNDED`）
- Ticket token：推測不能なランダム値（128bit以上、URL-safe）

## 8. 主要フロー

### 8.1 購入
1. `POST /api/checkout`
2. Event.remaining を **条件付き更新**（`remaining >= :qty` で `remaining -= :qty`）→ 失敗なら売切れエラー
3. Order を `PENDING` で作成
4. Stripe Checkout Session作成（`expires_at` = 30分後、`metadata.order_id` 付与）
5. フロントは `checkout_url` へリダイレクト

### 8.2 Webhook
- 署名検証（raw bodyを `await request.body()` で取得）
- `checkout.session.completed`
  - Order を条件付き更新 `PENDING → PAID`（既にPAIDなら何もしない＝冪等）
  - quantity分の Ticket を作成
  - SESでチケットメール送信（QR画像 + `/t/{token}` リンク）
- `checkout.session.expired`
  - Order を条件付き更新 `PENDING → EXPIRED`
  - 成功時のみ Event.remaining を quantity分戻す

### 8.3 受付
1. スタッフがQR読取 → `POST /api/staff/checkin { token }`
2. Ticket を条件付き更新（`attribute_not_exists(used_at)` で `used_at = now`）
3. 結果：成功＝OK / 条件失敗＝使用済み（使用時刻表示）/ 存在しない＝無効

## 9. 認証（スタッフ・管理者）

- 最小構成：パスワード → 署名付きトークン（JWT、短期有効）
- パスワードハッシュ・JWT秘密鍵は Secrets Manager or SSM Parameter Store（SecureString）
- 将来必要ならCognitoへ移行

## 10. メール（SES）

- 独自ドメインでDKIM/SPF/DMARC設定（Route53）
- サンドボックス解除申請が必要
- 送信内容：イベント名・日時・会場・枚数・QRコード（インライン画像 or チケットURL）
- 再送：管理画面から注文単位で再送（任意）

## 11. セキュリティ・運用

- カード情報は一切扱わない（Stripe Checkout）
- Stripe秘密鍵・Webhook秘密は Secrets Manager
- CORSは本番フロントのオリジンのみ許可
- API Gatewayのスロットリング設定（簡易DoS対策）
- CloudWatch Logs + エラー時アラーム（任意）
- DynamoDB ポイントインタイムリカバリ有効化

## 12. リポジトリ構成（案）

```
/
├── frontend/          # Vite + React
│   ├── src/api/       # APIクライアント（mock/live切替）
│   └── src/mocks/     # モックデータ
├── backend/           # FastAPI
│   ├── app/
│   └── tests/
├── infra/             # CDK (Python)
└── .github/workflows/
    ├── deploy-dev.yml   # main push → GitHub Pages（mock）
    └── deploy-prod.yml  # tag / production push → CDK deploy + S3同期
```

## 13. デプロイ上の注意

- Lambdaアーキテクチャ（arm64推奨）に合わせてpydantic-core等をビルド
  - `pip install --platform manylinux2014_aarch64 --only-binary=:all: -t ...` or コンテナイメージ
- コールドスタート（Python 1秒前後）は許容

## 14. 法務（公開前に用意）

- 特定商取引法に基づく表記（販売者名、連絡先、価格、支払時期、引渡時期、**返金不可の旨**、中止時の扱い）
- 利用規約（転売禁止、中止時の返金方針）
- プライバシーポリシー（取得情報：氏名・メール、利用目的）
- Stripeアカウント：団体代表者名義で登録・審査

## 15. 未決事項

- [ ] 1回あたりの最大販売枚数・1注文あたりの上限枚数
- [ ] 席種・価格区分の有無（現状は1イベント1価格）
- [ ] 無料イベント対応の要否（Stripeを通さない分岐）
- [ ] チケット譲渡・名義変更の可否
- [ ] ドメイン名
- [ ] 管理者・スタッフの人数とアカウント分けの要否
