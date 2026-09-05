import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'path';

// Vite 7.3.6 on Windows hard-deny: `isFileLoadingAllowed` rejects ANY path
// containing `~` before consulting `server.fs.allow` (a path-confusion
// guard, vite/dist/node/.../config.js `if (isWindows && filePath.includes("~"))`).
// This repo lives under `D:\~Vibe-Coding\`, so every client-environment
// file load fails — which vitest exercises through jsdom files
// (`transformMode: "web"`): each forked worker first runs
// `executeId('/@vite/env')` and then loads the jsdom test files through the
// client pipeline. Before this workaround that surfaced as 68 unhandled
// "Cannot find module '/@vite/env'" errors — and the 68 jsdom test files
// silently never ran (only the 21 node-environment files, 95 tests,
// actually executed).
//
// The hook below restores stock behaviour for `~`-rooted projects only: it
// serves files the fs guard would reject, while re-implementing the guard's
// remaining security checks (drive-letter colon confusion stays denied; the
// file must resolve to a real file). Machines whose path has no `~` (or on
// non-Windows platforms) keep the stock pipeline untouched.
function tildePathLoader() {
  return {
    name: 'tilde-path-loader-workaround',
    enforce: 'pre' as const,
    load(id: string) {
      if (process.platform !== 'win32' || !id.includes('~')) return undefined;
      const clean = id.split('?')[0];
      // Guard 1 (kept from upstream): deny `c:`-style colon confusion after
      // the drive letter — only one drive colon is ever valid on Windows.
      const withoutDrive = clean.replace(/^[A-Za-z]:/, '');
      if (withoutDrive.includes(':')) return undefined;
      try {
        const resolved = path.resolve(clean);
        if (!fs.statSync(resolved).isFile()) return undefined;
        return fs.readFileSync(resolved, 'utf-8');
      } catch {
        return undefined;
      }
    },
  };
}

export default defineConfig({
  plugins: [tildePathLoader(), react()],
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
