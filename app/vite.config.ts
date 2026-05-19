import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { inspectAttr } from 'plugin-inspect-react-code'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [inspectAttr(), react()],
  server: {
    // host: true binds both IPv4 (0.0.0.0) and IPv6 (::), so browsers
    // that resolve localhost to 127.0.0.1 reach the dev server. The
    // default ('localhost') sometimes binds IPv6-only on Windows, making
    // the UI look "down" to any IPv4 client.
    host: true,
    port: 3001,
    strictPort: false,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
