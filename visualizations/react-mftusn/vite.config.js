import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Single self-contained index.html for loading inside a PyQt5 QWebEngineView.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2020',
    minify: true,
    assetsInlineLimit: 100000000,
    chunkSizeWarningLimit: 10000,
  },
})
