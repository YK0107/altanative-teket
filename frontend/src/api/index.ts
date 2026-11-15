import type {
  AdminOrder,
  AdminSummary,
  BoxOfficeSaleRequest,
  BoxOfficeSaleResponse,
  CheckinResult,
  CheckoutRequest,
  CheckoutResponse,
  EventInfo,
  OrderInfo,
  SeatStatus,
  TicketInfo,
} from '../types'
import { mockApi } from './mock'
import { liveApi } from './live'

export interface Api {
  getEvent(): Promise<EventInfo>
  getSeatStatus(): Promise<SeatStatus>
  validateCoupon(code: string): Promise<boolean>
  checkout(req: CheckoutRequest): Promise<CheckoutResponse>
  cancelCheckout(sessionId: string): Promise<void>
  getOrderBySession(sessionId: string): Promise<OrderInfo>
  getOrder(orderId: string, orderKey: string): Promise<OrderInfo>
  getTicket(token: string): Promise<TicketInfo | null>
  // スタッフ（受付URLのキー）
  staffCheckin(key: string, token: string): Promise<CheckinResult>
  staffSearch(key: string, q: string): Promise<AdminOrder[]>
  staffCheckinOrder(key: string, orderId: string): Promise<void>
  boxOfficeSell(key: string, req: BoxOfficeSaleRequest): Promise<BoxOfficeSaleResponse>
  // 管理者
  adminLogin(password: string): Promise<string>
  adminSummary(jwt: string): Promise<AdminSummary>
  adminOrders(jwt: string): Promise<AdminOrder[]>
  adminResendEmail(jwt: string, orderId: string): Promise<void>
  adminCsvUrl(jwt: string): Promise<string>
}

export { ApiError } from './errors'

export const isMock = (import.meta.env.VITE_API_MODE ?? 'mock') === 'mock'
export const api: Api = isMock ? mockApi : liveApi
