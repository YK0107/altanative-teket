import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { SeatMap } from '../components/SeatMap'
import { CATEGORY_NAME, calcTotal, fmtDate, fmtTime, seatLabel, seatMap, yen } from '../lib/seats'
import type { EventInfo, SeatDef } from '../types'

export function EventPage() {
  const [ev, setEv] = useState<EventInfo | null>(null)
  const [sold, setSold] = useState<Set<string>>(new Set())
  const [held, setHeld] = useState<Set<string>>(new Set())
  const [floor, setFloor] = useState(1)
  const [selected, setSelected] = useState<string[]>([])
  const [msg, setMsg] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    const st = await api.getSeatStatus()
    setSold(new Set(st.sold))
    setHeld(new Set(st.held))
    // 他の人に取られた席は選択から外す
    setSelected((sel) => sel.filter((id) => !st.sold.includes(id) && !st.held.includes(id)))
  }, [])

  useEffect(() => {
    api.getEvent().then(setEv)
    refresh()
    const t = setInterval(refresh, 15000)
    return () => clearInterval(t)
  }, [refresh])

  const selSet = useMemo(() => new Set(selected), [selected])
  const freeByFloor = useMemo(() => {
    const m: Record<number, number> = { 1: 0, 2: 0, 3: 0 }
    for (const s of seatMap.seats) if (!sold.has(s.id) && !held.has(s.id)) m[s.f]++
    return m
  }, [sold, held])

  const toggle = (s: SeatDef) => {
    setMsg(null)
    if (selected.includes(s.id)) return setSelected(selected.filter((x) => x !== s.id))
    if (ev && selected.length >= ev.max_per_order) return setMsg(`1回のお申し込みは${ev.max_per_order}枚までです`)
    setSelected([...selected, s.id])
  }

  if (!ev) return <div className="loading">読み込み中…</div>

  return (
    <div className="page event-page">
      <section className="event-head card">
        <h1>{ev.name}</h1>
        <dl>
          <dt>日時</dt>
          <dd>
            {fmtDate(ev.starts_at)}
            <br />
            {fmtTime(ev.doors_open_at)}開場 {fmtTime(ev.starts_at)}開演
          </dd>
          <dt>会場</dt>
          <dd>{ev.venue}</dd>
          <dt>料金</dt>
          <dd>
            S席 {yen(ev.prices.S)} ／ A席 {yen(ev.prices.A)} ／ 車椅子席 {yen(ev.prices.W)}
          </dd>
        </dl>
        <p className="note">お支払い後のキャンセル・返金はできません（公演中止時を除く）。</p>
      </section>

      <section className="card seat-section">
        <div className="tabs" role="tablist">
          {seatMap.floors.map((f) => (
            <button key={f.f} role="tab" aria-selected={floor === f.f} className={floor === f.f ? 'active' : ''} onClick={() => setFloor(f.f)}>
              {f.name}
              <small>残 {freeByFloor[f.f]}</small>
            </button>
          ))}
        </div>
        <div className="legend">
          <span className="lg cat-S">S席 {yen(ev.prices.S)}</span>
          <span className="lg cat-A">A席 {yen(ev.prices.A)}</span>
          <span className="lg cat-W">車椅子 {yen(ev.prices.W)}</span>
          <span className="lg st-sel">選択中</span>
          <span className="lg st-held">手続き中</span>
          <span className="lg st-sold">販売済</span>
        </div>
        <SeatMap floor={floor} sold={sold} held={held} selected={selSet} onToggle={toggle} />
        <p className="hint">座席をタップして選択（最大{ev.max_per_order}枚）。ピンチ・ホイールで拡大できます。</p>
      </section>

      {msg && <div className="toast">{msg}</div>}
      <PurchasePanel ev={ev} selected={selected} onRemove={(id) => setSelected((s) => s.filter((x) => x !== id))} onConflict={refresh} />

      <footer className="legal-links">
        <Link to="/legal/tokushoho">特定商取引法に基づく表記</Link>
        <Link to="/legal/terms">利用規約</Link>
        <Link to="/legal/privacy">プライバシーポリシー</Link>
      </footer>
    </div>
  )
}

function PurchasePanel({ ev, selected, onRemove, onConflict }: { ev: EventInfo; selected: string[]; onRemove: (id: string) => void; onConflict: () => void }) {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [email2, setEmail2] = useState('')
  const [coupon, setCoupon] = useState('')
  const [couponState, setCouponState] = useState<'none' | 'checking' | 'ok' | 'ng'>('none')
  const [agree, setAgree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const couponCount = couponState === 'ok' ? selected.length : 0
  const { lines, total } = calcTotal(ev, selected, couponCount)

  const latestCoupon = useRef(coupon)
  latestCoupon.current = coupon
  const checkCoupon = async () => {
    const code = coupon.trim().toUpperCase()
    if (!code) return setCouponState('none')
    setCouponState('checking')
    let valid = false
    try {
      valid = await api.validateCoupon(code)
    } catch {
      /* 通信エラーは無効扱い（再入力で再確認） */
    }
    // 確認中にコードが書き換えられていたら結果を捨てる
    if (latestCoupon.current.trim().toUpperCase() === code) setCouponState(valid ? 'ok' : 'ng')
  }

  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  const canSubmit = selected.length > 0 && name.trim() && emailOk && email === email2 && agree && couponState !== 'checking' && couponState !== 'ng' && !busy

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      const res = await api.checkout({ seat_ids: selected, name: name.trim(), email, coupon_code: couponState === 'ok' ? coupon.trim().toUpperCase() : undefined })
      if (res.checkout_url) {
        // Stripe 以外への遷移は拒否（オープンリダイレクト対策）
        if (!res.checkout_url.startsWith('https://checkout.stripe.com/')) throw new Error('invalid checkout url')
        window.location.href = res.checkout_url
      } else {
        nav(`/purchase/success?order_id=${encodeURIComponent(res.order_id ?? '')}&key=${encodeURIComponent(res.order_key ?? '')}`)
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : '通信に失敗しました。時間をおいてお試しください。')
      if (e instanceof ApiError && e.code === 'seat_taken') onConflict()
      setBusy(false)
    }
  }

  if (selected.length === 0) return null

  return (
    <section className={`purchase-panel ${open ? 'open' : ''}`}>
      <button type="button" className="panel-bar" onClick={() => setOpen((o) => !o)}>
        <span>
          選択中 <b>{selected.length}</b> 枚
        </span>
        <span className="total">{yen(total)}</span>
        <span className="cta">{open ? '閉じる' : '購入手続きへ'}</span>
      </button>
      {open && (
        <form className="panel-body" onSubmit={submit}>
          <ul className="sel-list">
            {lines.map((l) => (
              <li key={l.seat.id}>
                <span className={`chip cat-${l.seat.c}`}>{CATEGORY_NAME[l.seat.c]}</span>
                <span className="seat-name">{seatLabel(l.seat)}</span>
                <span className="price">
                  {l.discount > 0 && <s>{yen(l.price)}</s>} {yen(l.subtotal)}
                </span>
                <button type="button" className="link" onClick={() => onRemove(l.seat.id)}>
                  解除
                </button>
              </li>
            ))}
          </ul>
          <label>
            クーポンコード（任意）
            <div className="row">
              <input value={coupon} onChange={(e) => (setCoupon(e.target.value), setCouponState('none'))} onBlur={checkCoupon} placeholder="例: ABCD1234" autoCapitalize="characters" />
              <button type="button" onClick={checkCoupon}>
                適用
              </button>
            </div>
            {couponState === 'ok' && <span className="ok">適用しました（1枚あたり{yen(ev.coupon_discount)}引き）</span>}
            {couponState === 'ng' && <span className="ng">無効なコードです</span>}
          </label>
          <label>
            お名前
            <input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" placeholder="山田 太郎" />
          </label>
          <label>
            メールアドレス（チケットをお送りします）
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" inputMode="email" />
          </label>
          <label>
            メールアドレス（確認）
            <input type="email" value={email2} onChange={(e) => setEmail2(e.target.value)} required autoComplete="off" inputMode="email" />
            {email2 && email !== email2 && <span className="ng">一致しません</span>}
          </label>
          <p className="note">携帯キャリアのメールは届かない場合があります。Gmail等のアドレスを推奨します。</p>
          <label className="check">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>
              <Link to="/legal/terms" target="_blank">
                利用規約
              </Link>
              に同意します（購入後のキャンセル・返金不可）
            </span>
          </label>
          {err && <div className="error">{err}</div>}
          <div className="sum">
            合計 <b>{yen(total)}</b>
          </div>
          <button className="primary" disabled={!canSubmit}>
            {busy ? '処理中…' : total === 0 ? '申し込む（お支払いなし）' : 'お支払いへ進む（カード決済）'}
          </button>
          {total > 0 && <p className="note">決済画面（Stripe）に移動します。座席は30分間確保されます。</p>}
        </form>
      )}
    </section>
  )
}
