import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// GitHub Pages(dev)では VITE_BASE=/<repo>/ を指定
export default defineConfig({
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
})
