import type { Api } from './index'
import { ApiError } from './errors'

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function req<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let code = 'error'
    let message = `通信エラー (${res.status})`
    try {
      const j = await res.json()
      code = j.code ?? code
      message = j.message ?? message
    } catch {
      /* empty */
    }
    throw new ApiError(res.status, code, message)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const staff = (key: string) => ({ 'X-Staff-Key': key })
const bearer = (jwt: string) => ({ Authorization: `Bearer ${jwt}` })

export const liveApi: Api = {
  getEvent: () => req('GET', '/api/event'),
  getSeatStatus: () => req('GET', '/api/event/seats'),
  validateCoupon: async (code) => (await req<{ valid: boolean }>('POST', '/api/coupons/validate', { code })).valid,
  checkout: (body) => req('POST', '/api/checkout', body),
  cancelCheckout: (sessionId) => req('POST', '/api/checkout/cancel', { session_id: sessionId }),
  getOrderBySession: (sessionId) => req('GET', `/api/orders/by-session/${encodeURIComponent(sessionId)}`),
  getOrder: (orderId, orderKey) =>
    req('GET', `/api/orders/${encodeURIComponent(orderId)}?key=${encodeURIComponent(orderKey)}`),
  getTicket: async (token) => {
    try {
      return await req('GET', `/api/tickets/${encodeURIComponent(token)}`)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  },
  staffCheckin: (key, token) => req('POST', '/api/staff/checkin', { token }, staff(key)),
  staffSearch: (key, q) => req('GET', `/api/staff/orders?q=${encodeURIComponent(q)}`, undefined, staff(key)),
  staffCheckinOrder: (key, orderId) => req('POST', `/api/staff/orders/${encodeURIComponent(orderId)}/checkin`, {}, staff(key)),
  boxOfficeSell: (key, body) => req('POST', '/api/staff/boxoffice', body, staff(key)),
  adminLogin: async (password) => (await req<{ token: string }>('POST', '/api/admin/login', { password })).token,
  adminSummary: (jwt) => req('GET', '/api/admin/summary', undefined, bearer(jwt)),
  adminOrders: (jwt) => req('GET', '/api/admin/orders', undefined, bearer(jwt)),
  adminResendEmail: (jwt, orderId) => req('POST', `/api/admin/orders/${encodeURIComponent(orderId)}/resend`, {}, bearer(jwt)),
  adminCsvUrl: async (jwt) => {
    const res = await fetch(BASE + '/api/admin/orders.csv', { headers: bearer(jwt) })
    if (!res.ok) throw new ApiError(res.status, 'error', 'CSV取得に失敗しました')
    return URL.createObjectURL(await res.blob())
  },
}
