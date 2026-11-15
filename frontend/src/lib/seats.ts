import raw from '../data/seats.json'
import type { EventInfo, SeatCategory, SeatDef, SeatMapData } from '../types'

export const seatMap = raw as unknown as SeatMapData
export const seatById = new Map<string, SeatDef>(seatMap.seats.map((s) => [s.id, s]))

export const CATEGORY_NAME: Record<SeatCategory, string> = { S: 'S席', A: 'A席', W: '車椅子席' }

export function seatLabel(s: SeatDef): string {
  if (s.c === 'W') return `1階 車椅子スペース ${s.n}`
  return `${s.a} ${s.r}列 ${s.n}番`
}

export function seatLabelById(id: string): string {
  const s = seatById.get(id)
  return s ? seatLabel(s) : id
}

/** 1枚あたりクーポン割引。0円未満にはならない */
export function calcTotal(ev: EventInfo, seatIds: string[], couponCount: number) {
  const lines = seatIds
    .map((id) => seatById.get(id))
    .filter((s): s is SeatDef => !!s)
    .map((s) => ({ seat: s, price: ev.prices[s.c] }))
    // 割引は高い席から適用（購入者に有利）
    .sort((a, b) => b.price - a.price)
  let remaining = couponCount
  const priced = lines.map((l) => {
    const discount = remaining > 0 ? Math.min(ev.coupon_discount, l.price) : 0
    if (remaining > 0) remaining--
    return { ...l, discount, subtotal: l.price - discount }
  })
  const total = priced.reduce((a, l) => a + l.subtotal, 0)
  return { lines: priced, total }
}

export const yen = (n: number) => `¥${n.toLocaleString('ja-JP')}`

export function fmtDateTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString('ja-JP', { timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit' })
}
