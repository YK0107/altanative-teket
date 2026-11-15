import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { CATEGORY_NAME, fmtDateTime, fmtTime } from '../lib/seats'
import type { TicketInfo } from '../types'

export function ticketUrl(token: string) {
  return `${window.location.origin}${import.meta.env.BASE_URL}t/${token}`
}

export function TicketCard({ t, compact }: { t: TicketInfo; compact?: boolean }) {
  const [qr, setQr] = useState<string>()
  useEffect(() => {
    QRCode.toDataURL(ticketUrl(t.token), { width: 480, margin: 1, errorCorrectionLevel: 'M' }).then(setQr)
  }, [t.token])
  return (
    <div className={`ticket ${t.used_at ? 'used' : ''} ${compact ? 'compact' : ''}`}>
      <div className="ticket-main">
        <div className="ticket-event">{t.event_name}</div>
        <div className="ticket-date">
          {fmtDateTime(t.starts_at)} 開演
          <br />
          {fmtTime(t.doors_open_at)} 開場 ／ {t.venue}
        </div>
        <div className="ticket-seat">
          <span className={`chip cat-${t.category}`}>{CATEGORY_NAME[t.category]}</span>
          {t.seat_label}
        </div>
        {!compact && <div className="ticket-holder">{t.holder_name} 様</div>}
      </div>
      <div className="ticket-qr">
        {qr && <img src={qr} alt="入場用QRコード" />}
        {t.used_at && <div className="used-stamp">使用済 {fmtTime(t.used_at)}</div>}
      </div>
    </div>
  )
}
