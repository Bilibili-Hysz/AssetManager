import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  base: '/',
  resolve: {
    preserveSymlinks: true,
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    fs: {
      allow: [path.resolve(__dirname)],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8080',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    // CI runners are slow enough that RTL act-flush timing occasionally
    // trips a wait-free assertion; one retry there, strict locally.
    retry: process.env.CI ? 1 : 0,
    coverage: {
      provider: 'istanbul',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/i18n/*.ts', 'src/vite-env.d.ts', 'src/main.tsx'],
      thresholds: {
        statements: 75,
        lines: 80,
        functions: 70,
        branches: 65,
      },
    },
  },
});
