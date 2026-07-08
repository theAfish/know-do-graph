import { defineConfig } from 'vite';

const API_TARGET = 'http://127.0.0.1:8000';
const PROXY_PATHS = ['/entries', '/graph', '/agent', '/mem', '/remote', '/health'];

export default defineConfig({
  base: './',
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      PROXY_PATHS.map((p) => [p, { target: API_TARGET, changeOrigin: true }]),
    ),
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
  },
});
