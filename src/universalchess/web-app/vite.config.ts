import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API target from environment variable or default
// For local dev, run: VITE_API_URL=http://localhost:5000 npm run dev
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
      '/analyse': {
        target: apiTarget,
        changeOrigin: true,
      },
      // Static assets from Flask (stockfish is in public/ now)
      '/static': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/logo': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/piece': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/resources': {
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
