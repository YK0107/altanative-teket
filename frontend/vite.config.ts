import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// GitHub Pages(dev)では VITE_BASE=/<repo>/ を指定
export default defineConfig({
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  // ローカルで live モードを試すとき: uvicorn(:8000) に /api を中継（本番は CloudFront で同一オリジン）
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
