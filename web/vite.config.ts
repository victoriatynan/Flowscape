import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so the built bundle works when served by the FastAPI backend
// at any mount point. In dev, /api and /ws proxy to the Python server, so
// `npm run dev` + `python Flowscape/api_server.py` work side by side.
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
