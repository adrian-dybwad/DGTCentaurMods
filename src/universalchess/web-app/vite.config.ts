import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API target from environment variable or default
const apiTarget = process.env.VITE_API_URL || 'http://dgt.local'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Proxy API calls to backend
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/events': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/fen': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/getgames': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/getpgn': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/deletegame': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/stockfish': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/piece': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
