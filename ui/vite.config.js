import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // minify disabled: rolldown's minifier mangles recharts' bundled lodash CJS modules into a
  // self-referential `var t=t()` (two bindings renamed to the same identifier), which throws
  // "t is not a function" at runtime on any recharts page. Unminified output avoids the collision.
  build: { outDir: 'dist', minify: false },
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
})
