import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Load env vars from .env files
  const env = loadEnv(mode, process.cwd(), '')
  
  // API target from VITE_API_URL environment variable or default
  // For local dev, run: VITE_API_URL=http://localhost:5000 npm run dev
  // Or use: ./scripts/run-react.sh --api http://localhost:5000
  const apiTarget = env.VITE_API_URL || process.env.VITE_API_URL || 'http://dgt.local'
  
  console.log(`[Vite] Proxying API calls to: ${apiTarget}`)
  
  return {
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
  }
})
