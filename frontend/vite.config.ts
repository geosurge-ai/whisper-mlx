import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API target can be overridden via VITE_API_TARGET env var (for E2E tests)
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:5997'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8792,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
