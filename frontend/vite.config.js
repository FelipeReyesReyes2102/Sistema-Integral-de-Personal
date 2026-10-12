import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// URL del backend FastAPI (se puede cambiar con la variable de entorno API_URL)
const API_URL = process.env.API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': API_URL,
    },
  },
})
