import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the UI runs on :5173 and proxies the API to the local backend.
// In production FastAPI serves the built files from frontend/dist on one port.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false } },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
})
