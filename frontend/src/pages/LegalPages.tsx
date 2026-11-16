import { Link } from 'react-router-dom'

// 文面は公開前に団体側で確定させること（ここは雛形）
const SELLER = import.meta.env.VITE_SELLER_NAME ?? '（団体名）'

function Legal({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="page legal">
      <section className="card">
        <h1>{title}</h1>
        {children}
        <p>
          <Link to="/">トップへ戻る</Link>
        </p>
      </section>
    </div>
  )
}

export function Tokushoho() {
  return (
    <Legal title="特定商取引法に基づく表記">
      <table className="kv">
        <tbody>
          <tr><th>販売事業者</th><td>{SELLER}</td></tr>
          <tr><th>運営責任者</th><td>（代表者氏名）</td></tr>
          <tr><th>所在地・電話番号</th><td>請求があった場合には遅滞なく開示いたします</td></tr>
          <tr><th>メールアドレス</th><td>（問い合わせ先）</td></tr>
          <tr><th>販売価格</th><td>各公演ページに記載（税込）</td></tr>
          <tr><th>商品代金以外の必要料金</th><td>なし（通信料はお客様負担）</td></tr>
          <tr><th>支払方法</th><td>クレジットカード（Stripe）／当日券は会場にて現金</td></tr>
          <tr><th>支払時期</th><td>購入手続き完了時</td></tr>
          <tr><th>引渡時期</th><td>決済完了後、電子チケットを即時メール送付</td></tr>
          <tr><th>返品・キャンセル</th><td>購入後のキャンセル・払い戻しはできません。公演中止の場合のみ全額返金いたします。</td></tr>
        </tbody>
      </table>
    </Legal>
  )
}

export function Terms() {
  return (
    <Legal title="利用規約">
      <ol>
        <li>購入後のキャンセル・変更・払い戻しはできません。</li>
        <li>公演が中止となった場合は、購入時のカードへ全額返金します。</li>
        <li>チケットの営利目的の転売を禁止します。</li>
        <li>QRコードは1枚につき1回のみ入場に使用できます。複製されたQRコードは最初に読み取られたもののみ有効です。</li>
        <li>クーポンコードは1枚あたり500円の割引となります。</li>
      </ol>
    </Legal>
  )
}

export function Privacy() {
  return (
    <Legal title="プライバシーポリシー">
      <p>取得する情報：氏名、メールアドレス</p>
      <p>利用目的：チケットの送付、公演に関する連絡（中止・変更等）、入場受付</p>
      <p>決済情報（カード番号等）は決済代行会社Stripeが管理し、当団体は保持しません。</p>
      <p>メールアドレスは決済代行会社Stripeが保持し、当団体のシステムには保存しません（チケット送付時のみ利用します）。</p>
      <p>取得した情報は公演終了後、一定期間経過後に削除します。</p>
    </Legal>
  )
}
