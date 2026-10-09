import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // host lets a phone on the local network open the app for door simulator testing.
    host: true,
    proxy: {
      // changeOrigin lets a phone on the local network reach Django through this proxy.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
})
