import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { CATEGORY_NAME, seatLabelById, yen } from '../lib/seats'
import type { AdminOrder, AdminSummary, SeatCategory } from '../types'

export function AdminPage() {
  const [jwt, setJwt] = useState(() => sessionStorage.getItem('adminJwt') ?? '')
  const logout = useCallback(() => (sessionStorage.removeItem('adminJwt'), setJwt('')), [])
  if (!jwt) return <Login onLogin={(t) => (sessionStorage.setItem('adminJwt', t), setJwt(t))} />
  return <Dashboard jwt={jwt} onExpired={logout} />
}

function Login({ onLogin }: { onLogin: (jwt: string) => void }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState<string | null>(null)
  return (
    <div className="page">
      <form
        className="login"
        onSubmit={async (e) => {
          e.preventDefault()
          try {
            onLogin(await api.adminLogin(pw))
          } catch (e) {
            setErr(e instanceof ApiError ? e.message : 'ログインに失敗しました')
          }
        }}
      >
        <h1>管理画面</h1>
        <label>
          パスワード
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
        </label>
        {err && <div className="error">{err}</div>}
        <button className="primary">ログイン</button>
      </form>
    </div>
  )
}

function Dashboard({ jwt, onExpired }: { jwt: string; onExpired: () => void }) {
  const [sum, setSum] = useState<AdminSummary | null>(null)
  const [orders, setOrders] = useState<AdminOrder[]>([])
  const [q, setQ] = useState('')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    // 期限切れ(401)ならログイン画面へ戻す
    const onErr = (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) onExpired()
      else setErr('読み込みに失敗しました')
    }
    api.adminSummary(jwt).then(setSum, onErr)
    api.adminOrders(jwt).then(setOrders, onErr)
  }, [jwt, onExpired])
  const filtered = orders.filter((o) => !q || `${o.name} ${o.order_id}`.toLowerCase().includes(q.toLowerCase()))
  const totalSold = sum ? Object.values(sum.sold).reduce((a, b) => a + b, 0) : 0

  return (
    <div className="page admin-page">
      <h1>販売状況</h1>
      {err && <div className="error">{err}</div>}
      {sum && (
        <div className="stats">
          <Stat label="販売済" value={`${totalSold} / ${sum.total_seats}`} />
          {(Object.keys(sum.sold) as SeatCategory[]).map((c) => (
            <Stat key={c} label={CATEGORY_NAME[c]} value={`${sum.sold[c]} 枚`} />
          ))}
          <Stat label="手続き中" value={`${sum.held} 席`} />
          <Stat label="売上（ネット）" value={yen(sum.revenue_online)} />
          <Stat label="売上（当日現金）" value={yen(sum.revenue_boxoffice)} />
          <Stat label="入場済" value={`${sum.checked_in} 人`} />
          <Stat label="クーポン利用" value={`${sum.coupon_used} 枚`} />
        </div>
      )}
      <section className="orders">
        <div className="row spread">
          <h2>注文一覧</h2>
          <div className="row">
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="検索" />
            <button
              onClick={async () => {
                const url = await api.adminCsvUrl(jwt)
                const a = document.createElement('a')
                a.href = url
                a.download = 'orders.csv'
                a.click()
              }}
            >
              CSV出力
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>日時</th>
                <th>経路</th>
                <th>氏名</th>
                <th>座席</th>
                <th>金額</th>
                <th>入場</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((o) => (
                <tr key={o.order_id}>
                  <td>{new Date(o.created_at).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })}</td>
                  <td>{o.channel === 'online' ? 'ネット' : '当日'}</td>
                  <td>
                    {o.name}
                  </td>
                  <td>{o.seats.map(seatLabelById).join('、')}</td>
                  <td>
                    {yen(o.amount)}
                    {o.coupon_code && <small> (クーポン)</small>}
                  </td>
                  <td>
                    {o.checked_in}/{o.seats.length}
                  </td>
                  <td>
                    {o.can_resend && (
                      <button
                        className="small"
                        onClick={() =>
                          api.adminResendEmail(jwt, o.order_id).then(
                            () => alert('再送しました'),
                            (e) => alert(e instanceof ApiError ? e.message : '再送に失敗しました'),
                          )
                        }
                      >
                        メール再送
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7}>注文はまだありません</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  )
}
