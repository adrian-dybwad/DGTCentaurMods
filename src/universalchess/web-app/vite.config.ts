import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Proxy API calls to Flask backend
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/events': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/fen': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/getgames': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/getpgn': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/deletegame': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/stockfish': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/piece': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
