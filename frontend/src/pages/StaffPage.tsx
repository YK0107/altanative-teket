import QrScanner from 'qr-scanner'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { SeatMap } from '../components/SeatMap'
import { calcTotal, fmtTime, seatLabel, seatLabelById, seatMap, yen } from '../lib/seats'
import type { AdminOrder, CheckinResult, EventInfo, SeatDef } from '../types'

// 受付URLは /staff#key=xxx 。フラグメントはサーバーに送られずアクセスログに残らない
function useStaffKey() {
  const [key] = useState(() => {
    const m = window.location.hash.match(/key=([^&]+)/)
    if (m) {
      sessionStorage.setItem('staffKey', decodeURIComponent(m[1]))
      history.replaceState(null, '', window.location.pathname)
    }
    return sessionStorage.getItem('staffKey') ?? ''
  })
  return key
}

export function StaffPage() {
  const key = useStaffKey()
  const [tab, setTab] = useState<'scan' | 'search' | 'box'>('scan')
  if (!key) return <div className="loading">受付用URLからアクセスしてください。</div>
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
  const [netErr, setNetErr] = useState<string | null>(null)
  const busy = useRef(false)
  // かざしたままのQRを再読取しないよう、直前のトークンは一定時間無視
  const last = useRef<{ token: string; at: number }>({ token: '', at: 0 })

  const check = async (raw: string, fromCamera: boolean) => {
    const token = extractToken(raw)
    if (!token || busy.current) return
    if (fromCamera && token === last.current.token && Date.now() - last.current.at < 8000) return
    busy.current = true
    last.current = { token, at: Date.now() }
    try {
      setResult(await api.staffCheckin(staffKey, token))
      setNetErr(null)
      navigator.vibrate?.(150)
    } catch (e) {
      setNetErr(e instanceof ApiError ? e.message : '通信エラー。もう一度読み取ってください')
      last.current = { token: '', at: 0 }
    }
    busy.current = false
  }
  const close = useCallback(() => setResult(null), [])

  useEffect(() => {
    if (!videoRef.current) return
    const sc = new QrScanner(videoRef.current, (r) => check(r.data, true), { highlightScanRegion: true, maxScansPerSecond: 5 })
    sc.start().catch(() => setCamErr('カメラを起動できません。ブラウザのカメラ許可を確認してください。'))
    return () => sc.destroy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="staff-pane">
      <div className="scanner">
        <video ref={videoRef} muted playsInline />
        {camErr && <div className="cam-err">{camErr}</div>}
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault()
          check(manual, false)
          setManual('')
        }}
      >
        <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="チケットURL/コードを手入力" />
        <button>照合</button>
      </form>
      {netErr && <div className="error">{netErr}</div>}
      {result && <CheckinResultView r={result} onClose={close} />}
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
    <section className="staff-pane">
      <form className="row" onSubmit={search}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="氏名・注文番号" />
        <button>検索</button>
      </form>
      {rows?.length === 0 && <p className="note">該当なし</p>}
      <ul className="order-list">
        {rows?.map((o) => (
          <li key={o.order_id}>
            <div>
              <b>{o.name}</b>
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

  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    const st = await api.getSeatStatus()
    setSold(new Set(st.sold))
    setHeld(new Set(st.held))
    // ネット販売で売れた席は選択から外す
    setSel((x) => x.filter((id) => !st.sold.includes(id) && !st.held.includes(id)))
  }, [])
  useEffect(() => {
    api.getEvent().then(setEv)
    refresh()
    const t = setInterval(refresh, 10000)
    return () => clearInterval(t)
  }, [refresh])
  const selSet = useMemo(() => new Set(sel), [sel])
  if (!ev) return null
  const { total } = calcTotal(ev, sel, Math.min(coupons, sel.length))

  const toggle = (s: SeatDef) => {
    if (sel.includes(s.id)) return setSel(sel.filter((i) => i !== s.id))
    if (sel.length >= ev.max_per_order) return setErr(`1回の販売は${ev.max_per_order}枚までです`)
    setErr(null)
    setSel([...sel, s.id])
  }
  const sell = async () => {
    if (busy) return
    setBusy(true)
    setErr(null)
    setDone(null)
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
    setBusy(false)
  }

  return (
    <section className="staff-pane">
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
          <input type="number" min={0} max={sel.length} value={coupons} onChange={(e) => setCoupons(Math.max(0, Math.floor(Number(e.target.value) || 0)))} style={{ width: '5em' }} />
        </label>
        <div className="sum">
          <span>お預かり金額（現金）</span>
          <b>{yen(total)}</b>
        </div>
        {err && <div className="error">{err}</div>}
        <button className="primary" disabled={sel.length === 0 || busy} onClick={sell}>
          {busy ? '処理中…' : '現金受領・販売確定（そのまま入場済み）'}
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
