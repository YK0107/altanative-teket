export type SeatCategory = 'S' | 'A' | 'W'

export interface SeatDef {
  id: string
  f: number // 階
  a: string // エリア表示名（1階, 2階LB ...）
  r: string // 列
  n: number // 番
  x: number
  y: number
  rot: number
  c: SeatCategory
}

export interface FloorDef {
  f: number
  name: string
  viewBox: [number, number, number, number]
}

export interface RowLabel {
  f: number
  t: string
  x: number
  y: number
}

export interface SeatMapData {
  venue: string
  floors: FloorDef[]
  seats: SeatDef[]
  labels: RowLabel[]
}

export interface EventInfo {
  id: string
  name: string
  starts_at: string // ISO8601
  doors_open_at: string
  venue: string
  sales_start: string
  sales_end: string
  on_sale: boolean
  prices: Record<SeatCategory, number>
  coupon_discount: number
  max_per_order: number
}

export interface SeatStatus {
  sold: string[]
  held: string[]
}

export interface CheckoutRequest {
  seat_ids: string[]
  coupon_code?: string
  name: string
  email: string
}

export interface CheckoutResponse {
  // 有料: Stripe Checkout へ遷移 / 0円: そのまま完了画面へ
  checkout_url?: string
  order_id?: string
}

export interface TicketInfo {
  token: string
  event_name: string
  starts_at: string
  doors_open_at: string
  venue: string
  seat_label: string
  category: SeatCategory
  holder_name: string
  used_at: string | null
}

export interface OrderInfo {
  order_id: string
  status: 'PENDING' | 'PAID' | 'EXPIRED' | 'REFUNDED'
  email: string
  tickets: TicketInfo[]
}

export type CheckinResult =
  | { result: 'ok'; ticket: TicketInfo }
  | { result: 'used'; ticket: TicketInfo }
  | { result: 'invalid' }

export interface BoxOfficeSaleRequest {
  seat_ids: string[]
  coupon_count: number // 当日券でクーポン適用する枚数
}

export interface BoxOfficeSaleResponse {
  order_id: string
  amount: number
}

export interface AdminSummary {
  total_seats: number
  sold: Record<SeatCategory, number>
  held: number
  revenue_online: number
  revenue_boxoffice: number
  checked_in: number
  coupon_used: number
}

export interface AdminOrder {
  order_id: string
  created_at: string
  channel: 'online' | 'boxoffice'
  name: string
  email: string
  seats: string[]
  amount: number
  coupon_code: string | null
  status: OrderInfo['status']
  checked_in: number
}
