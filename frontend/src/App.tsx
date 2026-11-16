import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { isMock } from './api'
import { AdminPage } from './pages/AdminPage'
import { EventPage } from './pages/EventPage'
import { Privacy, Terms, Tokushoho } from './pages/LegalPages'
import { PurchaseCancel, PurchaseSuccess, TicketPage } from './pages/PurchasePages'
import { StaffPage } from './pages/StaffPage'

const SITE = import.meta.env.VITE_SITE_NAME ?? 'チケット'

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <header className="site-header">
        <Link to="/">{SITE}</Link>
        {isMock && <span className="mock-badge">DEMO</span>}
      </header>
      <main>
        <Routes>
          <Route path="/" element={<EventPage />} />
          <Route path="/purchase/success" element={<PurchaseSuccess />} />
          <Route path="/purchase/cancel" element={<PurchaseCancel />} />
          <Route path="/t/:token" element={<TicketPage />} />
          <Route path="/staff" element={<StaffPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/legal/tokushoho" element={<Tokushoho />} />
          <Route path="/legal/terms" element={<Terms />} />
          <Route path="/legal/privacy" element={<Privacy />} />
          <Route path="*" element={<div className="loading">ページが見つかりません</div>} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
