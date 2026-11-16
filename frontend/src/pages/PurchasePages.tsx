import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { TicketCard, ticketUrl } from '../components/TicketCard'
import type { OrderInfo, TicketInfo } from '../types'

export function PurchaseSuccess() {
  const [q] = useSearchParams()
  const sessionId = q.get('session_id')
  const orderId = q.get('order_id') ?? ''
  const orderKey = q.get('key') ?? ''
  const [order, setOrder] = useState<OrderInfo | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let tries = 0
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const MAX_TRIES = 40 // 約60秒
    const load = async () => {
      let o: OrderInfo | null = null
      try {
        o = sessionId ? await api.getOrderBySession(sessionId) : await api.getOrder(orderId, orderKey)
      } catch {
        /* 一時的な通信エラーはリトライ */
      }
      if (cancelled) return
      if (o) setOrder(o)
      // Webhook 到着待ち（PENDING の間 or エラー時はポーリング）
      if ((!o || o.status === 'PENDING') && ++tries < MAX_TRIES) timer = setTimeout(load, 1500)
      else if (!o || o.status === 'PENDING')
        setErr('決済の確認に時間がかかっています。数分後にメールをご確認いただくか、このページを再読み込みしてください。')
    }
    load()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [sessionId, orderId, orderKey])

  return (
    <div className="page narrow">
      <section className="message">
        <h1>お申し込みありがとうございました</h1>
        {err && <p className="error">{err}</p>}
        {!order && !err && <p>確認中…</p>}
        {order?.status === 'PENDING' && !err && <p>決済を確認しています…</p>}
        {order?.status === 'PAID' && (
          <p>
            ご入力のメールアドレスにチケットをお送りしました。
            <br />
            メールが届かない場合も、下のチケットを当日ご提示いただければ入場できます。
            <br />
            <b>このページをブックマークするか、各チケットのリンクを保存してください。</b>
          </p>
        )}
      </section>
      {order && order.tickets.length > 0 && (
        <div className="ticket-list">
          {order.tickets.map((t) => (
            <div key={t.token} className="ticket-wrap">
              <TicketCard t={t} compact />
              <a href={ticketUrl(t.token)} className="ticket-link">
                このチケットを開く
              </a>
            </div>
          ))}
        </div>
      )}
      <p className="back">
        <Link to="/">トップへ戻る</Link>
      </p>
    </div>
  )
}

export function PurchaseCancel() {
  const [q] = useSearchParams()
  const sessionId = q.get('session_id')
  useEffect(() => {
    // 中断したら即座に座席を解放
    if (sessionId) api.cancelCheckout(sessionId).catch(() => {})
  }, [sessionId])
  return (
    <div className="page narrow">
      <section className="message">
        <h1>お手続きを中断しました</h1>
        <p>決済は行われていません。選択した座席は解放されました。</p>
        <Link className="button primary" to="/">
          座席選択に戻る
        </Link>
      </section>
    </div>
  )
}

export function TicketPage() {
  const { token = '' } = useParams()
  const [t, setT] = useState<TicketInfo | null | undefined>(undefined)
  useEffect(() => {
    api.getTicket(token).then(setT)
  }, [token])
  if (t === undefined) return <div className="loading">読み込み中…</div>
  if (t === null)
    return (
      <div className="page narrow">
        <section className="message">
          <h1>チケットが見つかりません</h1>
          <p>URLをご確認ください。</p>
        </section>
      </div>
    )
  return (
    <div className="page ticket-page">
      <TicketCard t={t} />
      <p className="note">入場時にこの画面のQRコードを受付スタッフにご提示ください。スクリーンショットでも入場できます。</p>
    </div>
  )
}
