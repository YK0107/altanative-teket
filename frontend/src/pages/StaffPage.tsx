import QrScanner from 'qr-scanner'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { SeatMap } from '../components/SeatMap'
import { calcTotal, fmtTime, seatLabel, seatLabelById, seatMap, yen } from '../lib/seats'
import type { AdminOrder, CheckinResult, EventInfo, SeatDef } from '../types'

function useStaffKey() {
  const [q] = useSearchParams()
  const fromUrl = q.get('key')
  if (fromUrl) sessionStorage.setItem('staffKey', fromUrl)
  return fromUrl ?? sessionStorage.getItem('staffKey') ?? ''
}

export function StaffPage() {
  const key = useStaffKey()
  const [tab, setTab] = useState<'scan' | 'search' | 'box'>('scan')
  if (!key) return <div className="page card center">受付用URLからアクセスしてください。</div>
  return (
    <div className="page staff-page">
      <div className="tabs staff-tabs">
        <button className={tab === 'scan' ? 'active' : ''} onClick={() => setTab('scan')}>
          QR受付
        </button>
        <button className={tab === 'search' ? 'active' : ''} onClick={() => setTab('search')}>
          名前検索
        </button>
        <button className={tab === 'box' ? 'active' : ''} onClick={() => setTab('box')}>
          当日券
        </button>
      </div>
      {tab === 'scan' && <ScanTab staffKey={key} />}
      {tab === 'search' && <SearchTab staffKey={key} />}
      {tab === 'box' && <BoxOfficeTab staffKey={key} />}
    </div>
  )
}

function extractToken(text: string) {
  const m = text.match(/\/t\/([A-Za-z0-9_-]+)/)
  return m ? m[1] : text.trim()
}

function ScanTab({ staffKey }: { staffKey: string }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [result, setResult] = useState<CheckinResult | null>(null)
  const [camErr, setCamErr] = useState<string | null>(null)
  const [manual, setManual] = useState('')
  const busy = useRef(false)

  const check = async (raw: string) => {
    if (busy.current) return
    busy.current = true
    try {
      setResult(await api.staffCheckin(staffKey, extractToken(raw)))
      navigator.vibrate?.(150)
    } catch (e) {
      setCamErr(e instanceof ApiError ? e.message : '通信エラー')
    }
    setTimeout(() => {
      busy.current = false
    }, 1500)
  }

  useEffect(() => {
    if (!videoRef.current) return
    const sc = new QrScanner(videoRef.current, (r) => check(r.data), { highlightScanRegion: true, maxScansPerSecond: 5 })
    sc.start().catch(() => setCamErr('カメラを起動できません。ブラウザのカメラ許可を確認してください。'))
    return () => sc.destroy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="card">
      <div className="scanner">
        <video ref={videoRef} muted playsInline />
        {camErr && <div className="cam-err">{camErr}</div>}
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault()
          check(manual)
          setManual('')
        }}
      >
        <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="チケットURL/コードを手入力" />
        <button>照合</button>
      </form>
      {result && <CheckinResultView r={result} onClose={() => setResult(null)} />}
    </section>
  )
}

function CheckinResultView({ r, onClose }: { r: CheckinResult; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, r.result === 'ok' ? 2500 : 6000)
    return () => clearTimeout(t)
  }, [r, onClose])
  return (
    <div className={`checkin-result res-${r.result}`} onClick={onClose}>
      <div className="big">{r.result === 'ok' ? 'OK' : r.result === 'used' ? '使用済み' : '無効'}</div>
      {r.result !== 'invalid' && (
        <div className="detail">
          {r.ticket.seat_label}
          <br />
          {r.ticket.holder_name} 様
          {r.result === 'used' && r.ticket.used_at && <div>入場時刻 {fmtTime(r.ticket.used_at)}</div>}
        </div>
      )}
      {r.result === 'invalid' && <div className="detail">このQRコードは本公演のチケットではありません</div>}
      <div className="tap">タップで閉じる</div>
    </div>
  )
}

function SearchTab({ staffKey }: { staffKey: string }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<AdminOrder[] | null>(null)
  const search = async (e?: React.FormEvent) => {
    e?.preventDefault()
    setRows(await api.staffSearch(staffKey, q))
  }
  return (
    <section className="card">
      <form className="row" onSubmit={search}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="氏名・メール・注文番号" />
        <button>検索</button>
      </form>
      {rows?.length === 0 && <p>該当なし</p>}
      <ul className="order-list">
        {rows?.map((o) => (
          <li key={o.order_id}>
            <div>
              <b>{o.name}</b> <small>{o.email}</small>
            </div>
            <div className="seats">{o.seats.map(seatLabelById).join('、')}</div>
            <div className="row">
              <span>
                入場 {o.checked_in}/{o.seats.length}
              </span>
              <button
                disabled={o.checked_in >= o.seats.length}
                onClick={async () => {
                  if (!confirm(`${o.name} 様の ${o.seats.length} 枚をまとめて入場処理しますか？`)) return
                  await api.staffCheckinOrder(staffKey, o.order_id)
                  search()
                }}
              >
                全員入場
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function BoxOfficeTab({ staffKey }: { staffKey: string }) {
  const [ev, setEv] = useState<EventInfo | null>(null)
  const [sold, setSold] = useState<Set<string>>(new Set())
  const [held, setHeld] = useState<Set<string>>(new Set())
  const [floor, setFloor] = useState(1)
  const [sel, setSel] = useState<string[]>([])
  const [coupons, setCoupons] = useState(0)
  const [done, setDone] = useState<{ amount: number; seats: string[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const refresh = async () => {
    const st = await api.getSeatStatus()
    setSold(new Set(st.sold))
    setHeld(new Set(st.held))
  }
  useEffect(() => {
    api.getEvent().then(setEv)
    refresh()
  }, [])
  const selSet = useMemo(() => new Set(sel), [sel])
  if (!ev) return null
  const { total } = calcTotal(ev, sel, Math.min(coupons, sel.length))

  const toggle = (s: SeatDef) => setSel((x) => (x.includes(s.id) ? x.filter((i) => i !== s.id) : [...x, s.id]))
  const sell = async () => {
    setErr(null)
    try {
      const r = await api.boxOfficeSell(staffKey, { seat_ids: sel, coupon_count: Math.min(coupons, sel.length) })
      setDone({ amount: r.amount, seats: sel })
      setSel([])
      setCoupons(0)
      refresh()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : '通信エラー')
      refresh()
    }
  }

  return (
    <section className="card">
      <div className="tabs">
        {seatMap.floors.map((f) => (
          <button key={f.f} className={floor === f.f ? 'active' : ''} onClick={() => setFloor(f.f)}>
            {f.name}
          </button>
        ))}
      </div>
      <SeatMap floor={floor} sold={sold} held={held} selected={selSet} onToggle={toggle} />
      <div className="box-panel">
        <div>
          選択 {sel.length} 枚：{sel.map((id) => seatLabel(seatMap.seats.find((s) => s.id === id)!)).join('、') || '—'}
        </div>
        <label className="row">
          クーポン提示枚数
          <input type="number" min={0} max={sel.length} value={coupons} onChange={(e) => setCoupons(Number(e.target.value))} style={{ width: '5em' }} />
        </label>
        <div className="sum">
          お預かり金額 <b>{yen(total)}</b>（現金）
        </div>
        {err && <div className="error">{err}</div>}
        <button className="primary" disabled={sel.length === 0} onClick={sell}>
          現金受領・販売確定（そのまま入場済み）
        </button>
        {done && (
          <div className="ok-box">
            販売しました：{done.seats.map(seatLabelById).join('、')} ／ {yen(done.amount)}
          </div>
        )}
      </div>
    </section>
  )
}
