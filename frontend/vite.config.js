import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = process.env.VITE_API_URL || 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
      '/health': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
})
