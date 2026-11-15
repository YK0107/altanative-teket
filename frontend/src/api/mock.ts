// dev(GitHub Pages)/スクショ用のインメモリモック。状態は localStorage に保存。
import type { Api } from './index'
import { ApiError } from './errors'
import type { AdminOrder, EventInfo, OrderInfo, TicketInfo } from '../types'
import { calcTotal, seatById, seatLabelById, seatMap } from '../lib/seats'

const EVENT: EventInfo = {
  id: 'evt_2027',
  name: '一橋大学管弦楽団 第74回定期演奏会',
  starts_at: '2026-12-02T09:30:00Z',
  doors_open_at: '2026-12-02T08:30:00Z',
  venue: '東京芸術劇場 コンサートホール',
  sales_start: '2026-11-15T01:00:00Z',
  sales_end: '2026-12-02T08:30:00Z',
  on_sale: true,
  prices: { S: 1000, A: 500, W: 500 },
  coupon_discount: 500,
  max_per_order: 10,
}
const COUPONS = new Set(['SAMPLE500', 'FRIEND'])
const STAFF_KEY = 'demo'

interface State {
  orders: (AdminOrder & { tokens: string[]; order_key: string })[]
  tickets: Record<string, TicketInfo & { order_id: string }>
}

// 決定的な疑似乱数で「売れている席」を作る
function seededSold(): string[] {
  let x = 42
  const rnd = () => ((x = (x * 1103515245 + 12345) % 2 ** 31) / 2 ** 31)
  return seatMap.seats.filter((s) => (s.f === 1 && s.y < 330 ? rnd() < 0.55 : rnd() < 0.18)).map((s) => s.id)
}
const BASE_SOLD = seededSold()
const BASE_HELD = seatMap.seats.filter((s) => s.f === 1 && s.r === 'K' && s.n >= 16 && s.n <= 19).map((s) => s.id)

const KEY = 'teket-alt-mock'
function load(): State {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) ?? '')
    if (s && s.orders) return s
  } catch {
    /* empty */
  }
  return { orders: [], tickets: {} }
}
function save(s: State) {
  localStorage.setItem(KEY, JSON.stringify(s))
}

const wait = (ms = 250) => new Promise((r) => setTimeout(r, ms))
const rid = (n = 16) =>
  Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => 'abcdefghijklmnopqrstuvwxyz0123456789'[b % 36]).join('')

function soldIds(st: State) {
  return new Set([...BASE_SOLD, ...st.orders.flatMap((o) => o.seats)])
}

function createOrder(st: State, seatIds: string[], name: string, email: string, coupon: string | null, channel: 'online' | 'boxoffice', couponCount: number) {
  const sold = soldIds(st)
  for (const id of seatIds) {
    if (sold.has(id) || BASE_HELD.includes(id)) throw new ApiError(409, 'seat_taken', `${seatLabelById(id)} は${BASE_HELD.includes(id) ? '他の方が購入手続き中' : '販売済み'}です`)
  }
  const order_id = 'ord_' + rid(12)
  const { total } = calcTotal(EVENT, seatIds, couponCount)
  const tokens: string[] = []
  for (const id of seatIds) {
    const token = rid(22)
    tokens.push(token)
    st.tickets[token] = {
      token,
      order_id,
      event_name: EVENT.name,
      starts_at: EVENT.starts_at,
      doors_open_at: EVENT.doors_open_at,
      venue: EVENT.venue,
      seat_label: seatLabelById(id),
      category: seatById.get(id)!.c,
      holder_name: name,
      used_at: channel === 'boxoffice' ? new Date().toISOString() : null,
    }
  }
  const order = {
    order_id,
    created_at: new Date().toISOString(),
    channel,
    name,
    email,
    seats: seatIds,
    amount: total,
    coupon_code: coupon,
    status: 'PAID' as const,
    checked_in: channel === 'boxoffice' ? seatIds.length : 0,
    tokens,
    order_key: rid(32),
  }
  st.orders.unshift(order)
  save(st)
  return order
}

function toOrderInfo(st: State, o: State['orders'][number]): OrderInfo {
  return { order_id: o.order_id, status: o.status, email: o.email, tickets: o.tokens.map((t) => st.tickets[t]) }
}

export const mockApi: Api = {
  async getEvent() {
    await wait()
    return EVENT
  },
  async getSeatStatus() {
    await wait()
    const st = load()
    return { sold: [...soldIds(st)], held: BASE_HELD }
  },
  async validateCoupon(code) {
    await wait()
    return COUPONS.has(code.trim().toUpperCase())
  },
  async checkout(req) {
    await wait(500)
    if (req.seat_ids.length === 0 || req.seat_ids.length > EVENT.max_per_order) throw new ApiError(400, 'bad_quantity', '枚数が不正です')
    const coupon = req.coupon_code ? req.coupon_code.trim().toUpperCase() : null
    if (coupon && !COUPONS.has(coupon)) throw new ApiError(400, 'bad_coupon', 'クーポンコードが無効です')
    const st = load()
    // モックでは Stripe を経由せず即決済完了扱い
    const o = createOrder(st, req.seat_ids, req.name, req.email, coupon, 'online', coupon ? req.seat_ids.length : 0)
    return { order_id: o.order_id, order_key: o.order_key }
  },
  async cancelCheckout() {
    await wait()
  },
  async getOrderBySession() {
    throw new ApiError(404, 'not_found', 'モックでは Stripe セッションはありません')
  },
  async getOrder(orderId, orderKey) {
    await wait()
    const st = load()
    const o = st.orders.find((x) => x.order_id === orderId && x.order_key === orderKey)
    if (!o) throw new ApiError(404, 'not_found', '注文が見つかりません')
    return toOrderInfo(st, o)
  },
  async getTicket(token) {
    await wait()
    const t = load().tickets[token]
    if (t) return t
    if (token === 'demo') {
      return {
        token: 'demo',
        event_name: EVENT.name,
        starts_at: EVENT.starts_at,
        doors_open_at: EVENT.doors_open_at,
        venue: EVENT.venue,
        seat_label: '1階 H列 18番',
        category: 'S',
        holder_name: '山田 太郎',
        used_at: null,
      }
    }
    return null
  },
  async staffCheckin(key, token) {
    await wait()
    if (key !== STAFF_KEY) throw new ApiError(401, 'unauthorized', '受付URLが無効です')
    const st = load()
    const t = st.tickets[token]
    if (!t) return { result: 'invalid' }
    if (t.used_at) return { result: 'used', ticket: t }
    t.used_at = new Date().toISOString()
    const o = st.orders.find((x) => x.order_id === t.order_id)
    if (o) o.checked_in++
    save(st)
    return { result: 'ok', ticket: t }
  },
  async staffSearch(key, q) {
    await wait()
    if (key !== STAFF_KEY) throw new ApiError(401, 'unauthorized', '受付URLが無効です')
    const s = q.trim().toLowerCase()
    if (!s) return []
    return load()
      .orders.filter((o) => o.name.toLowerCase().includes(s) || o.email.toLowerCase().includes(s) || o.order_id.includes(s))
      .map(({ order_key: _k, tokens: _t, ...o }) => o)
  },
  async staffCheckinOrder(key, orderId) {
    await wait()
    if (key !== STAFF_KEY) throw new ApiError(401, 'unauthorized', '受付URLが無効です')
    const st = load()
    const o = st.orders.find((x) => x.order_id === orderId)
    if (!o) throw new ApiError(404, 'not_found', '注文が見つかりません')
    for (const t of o.tokens) st.tickets[t].used_at ??= new Date().toISOString()
    o.checked_in = o.tokens.length
    save(st)
  },
  async boxOfficeSell(key, req) {
    await wait()
    if (key !== STAFF_KEY) throw new ApiError(401, 'unauthorized', '受付URLが無効です')
    const st = load()
    const o = createOrder(st, req.seat_ids, '当日券', '', req.coupon_count > 0 ? '(当日)' : null, 'boxoffice', req.coupon_count)
    return { order_id: o.order_id, amount: o.amount }
  },
  async adminLogin(password) {
    await wait()
    if (password !== 'admin') throw new ApiError(401, 'unauthorized', 'パスワードが違います')
    return 'mock-jwt'
  },
  async adminSummary() {
    await wait()
    const st = load()
    const sold = soldIds(st)
    const cnt = { S: 0, A: 0, W: 0 }
    for (const id of sold) cnt[seatById.get(id)!.c]++
    const sum = (ch: string) => st.orders.filter((o) => o.channel === ch).reduce((a, o) => a + o.amount, 0)
    return {
      total_seats: seatMap.seats.length,
      sold: cnt,
      held: BASE_HELD.length,
      revenue_online: sum('online') + BASE_SOLD.length * 800,
      revenue_boxoffice: sum('boxoffice'),
      checked_in: st.orders.reduce((a, o) => a + o.checked_in, 0),
      coupon_used: st.orders.filter((o) => o.coupon_code).reduce((a, o) => a + o.seats.length, 0),
    }
  },
  async adminOrders() {
    await wait()
    return load().orders.map(({ order_key: _k, tokens: _t, ...o }) => o)
  },
  async adminResendEmail() {
    await wait()
  },
  async adminCsvUrl() {
    const rows = [['注文ID', '日時', '経路', '氏名', 'メール', '座席', '金額', 'クーポン', '入場済']]
    for (const o of load().orders) {
      rows.push([o.order_id, o.created_at, o.channel, o.name, o.email, o.seats.map(seatLabelById).join(' / '), String(o.amount), o.coupon_code ?? '', String(o.checked_in)])
    }
    // CSVインジェクション対策: 数式扱いされる先頭文字をエスケープ
    const cell = (c: string) => `"${(/^[=+\-@\t\r]/.test(c) ? "'" + c : c).replaceAll('"', '""')}"`
    const csv = '\ufeff' + rows.map((r) => r.map(cell).join(',')).join('\r\n')
    return URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  },
}
