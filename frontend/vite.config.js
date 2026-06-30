import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true
  },
  css: {
    // This tells Vite to IGNORE any stray postcss.config files outside this folder!
    postcss: {} 
  }
})