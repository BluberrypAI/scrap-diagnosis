import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// /api → FastAPI(기본 http://127.0.0.1:8030). 서버 라우트는 루트(/cases, /companies …)라 접두어를 뗀다.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8030';
  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT || 5180),
      strictPort: true,
      proxy: {
        '/api': { target, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.js'],
      css: false,
      env: { VITE_USE_MOCK: '0', VITE_MOCK_DELAY: '0' },
    },
  };
});
