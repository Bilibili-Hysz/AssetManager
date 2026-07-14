# WebUI React 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AssetsManager 现有原生 JS MPA 前端替换为 React + TypeScript + Vite + Tailwind CSS 的 SPA，位于 `webui/` 目录，保持与现有后端完全兼容。

**Architecture:** 单页应用 (SPA)，React Router 管理路由，API 层通过 fetch 调用后端 REST 端点，AuthContext 管理认证状态，自定义 hooks 管理页面数据和缓存。

**Tech Stack:** React 18, TypeScript 5, Vite 5, React Router 6, Tailwind CSS 3, lucide-react

## 全局约束

- 所有组件使用 TypeScript + 函数组件 + hooks
- 不使用任何 UI 组件库（无 shadcn/ui、Ant Design、MUI 等）
- 不使用状态管理库（无 Zustand、Redux），仅用 React Context + hooks
- 样式仅使用 Tailwind CSS utility classes（无 CSS Modules、styled-components）
- 所有文本展示需通过 i18n 模块，不硬编码中/英/日文字符串
- API 调用统一通过 `src/api/client.ts` 封装的 fetch 实例
- 每个 API 响应类型在 `src/types/api.ts` 中定义
- 新文件统一使用 PascalCase 命名组件文件，camelCase 命名工具/hook 文件
- 路由路径设计需与现有后端认证豁免路径匹配（`/api/auth/login`、`/api/info` 等不需要 token）
- 构建输出目录为 `webui/dist/`

---

## Task 1: 项目脚手架搭建

**Covers:** [S2, S3]

**Files:**
- Create: `webui/package.json`
- Create: `webui/tsconfig.json`
- Create: `webui/tsconfig.node.json`
- Create: `webui/vite.config.ts`
- Create: `webui/tailwind.config.ts`
- Create: `webui/postcss.config.js`
- Create: `webui/index.html`
- Create: `webui/src/main.tsx`
- Create: `webui/src/App.tsx`
- Create: `webui/src/index.css`
- Create: `webui/src/vite-env.d.ts`

**Interfaces:**
- Produces: Vite dev server on port 5173，代理 `/api` `/ws` `/static` 到后端

**Step 1: 创建 package.json**

webui/package.json:
```json
{
  "name": "assets-manager-webui",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "lucide-react": "^0.460.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.4",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.49",
    "tailwindcss": "^3.4.15",
    "typescript": "^5.6.3",
    "vite": "^5.4.11"
  }
}
```

**Step 2: 创建 tsconfig.json**

webui/tsconfig.json:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "paths": {
      "@/*": ["./src/*"]
    },
    "baseUrl": "."
  },
  "include": ["src"]
}
```

**Step 3: 创建 tsconfig.node.json**

webui/tsconfig.node.json:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["vite.config.ts"]
}
```

**Step 4: 创建 vite.config.ts**

webui/vite.config.ts:
```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8080',
        ws: true,
      },
      '/static': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
```

**Step 5: 创建 tailwind.config.ts**

webui/tailwind.config.ts:
```typescript
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
          950: '#1e1b4b',
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
```

**Step 6: 创建 postcss.config.js**

webui/postcss.config.js:
```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

**Step 7: 创建 index.html**

webui/index.html:
```html
<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/static/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
    <title>AssetManager</title>
  </head>
  <body class="bg-slate-950 text-slate-100 font-sans">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**Step 8: 创建 src/vite-env.d.ts**

webui/src/vite-env.d.ts:
```typescript
/// <reference types="vite/client" />
```

**Step 9: 创建 src/index.css**

webui/src/index.css:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  * {
    @apply border-slate-700/50;
  }

  body {
    @apply bg-slate-950 text-slate-100 antialiased;
  }

  :root {
    --color-bg: #020617;
    --color-surface: #0f172a;
    --color-border: #334155;
  }

  .light {
    --color-bg: #f8fafc;
    --color-surface: #ffffff;
    --color-border: #e2e8f0;
  }

  ::-webkit-scrollbar {
    @apply w-2;
  }

  ::-webkit-scrollbar-track {
    @apply bg-transparent;
  }

  ::-webkit-scrollbar-thumb {
    @apply bg-slate-700/50 rounded-full;
  }

  ::-webkit-scrollbar-thumb:hover {
    @apply bg-slate-600/50;
  }
}

@layer components {
  .skeleton {
    @apply bg-slate-800/50 rounded animate-pulse;
  }
}
```

**Step 10: 创建 src/main.tsx**

webui/src/main.tsx:
```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

**Step 11: 创建 src/App.tsx**

webui/src/App.tsx:
```typescript
function App() {
  return (
    <div className="flex items-center justify-center h-screen">
      <h1 className="text-2xl font-semibold text-slate-300">AssetManager WebUI</h1>
    </div>
  );
}

export default App;
```

**Step 12: 安装依赖并验证**
```bash
cd webui
npm install
npx tsc --noEmit
```



## Task 2: API 层 - 类型定义和客户端

**Covers:** [S3, S7]

**Files:**
- Create: `webui/src/types/api.ts`
- Create: `webui/src/api/client.ts`

**Interfaces:**
- Consumes: Task 1 脚手架
- Produces: `src/types/api.ts` 中所有类型定义，`src/api/client.ts` 中 `createApiClient`

**Step 1: 创建 src/types/api.ts**

webui/src/types/api.ts:
```typescript
export interface ServerInfo {
  version: string;
  share_name: string;
  library_root: string;
  auth_enabled: boolean;
  auth_mode: 'none' | 'password' | 'key' | 'user';
  theme_color: string;
  welcome_msg: string;
  footer_text: string;
  library_stats: {
    total_projects: number;
    total_size: number;
    total_size_fmt: string;
  };
}

export interface LoginResponse {
  token: string;
  user?: User;
}

export interface RegisterResponse {
  token: string;
  user: User;
}

export interface User {
  id: number;
  username: string;
  role: 'admin' | 'user';
  active: boolean;
  created_at: string;
  last_login?: string;
}

export interface MeResponse {
  user: User;
}

export interface ProjectItem {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size: number;
  size_fmt: string;
  modified: number;
  extension: string;
  category: string;
  thumbnail_url?: string;
}

export interface FilesResponse {
  current_path: string;
  parent_path: string | null;
  items: ProjectItem[];
  total_count: number;
  total_size: number;
  total_size_fmt: string;
}

export interface ProjectDetail {
  name: string;
  path: string;
  type: string;
  size: number;
  size_fmt: string;
  modified: number;
  items?: ProjectItem[];
  images?: string[];
  tags?: string[];
  notes?: string;
  urls?: string[];
}

export interface TreeItem {
  name: string;
  path: string;
  type: 'file' | 'dir';
  children?: TreeItem[];
}

export interface HomeData {
  total_projects: number;
  total_size: number;
  total_size_fmt: string;
  recent_projects: ProjectItem[];
  categories: Record<string, number>;
}

export interface SearchResult {
  name: string;
  path: string;
  type: string;
  extension: string;
  category: string;
  thumbnail_url?: string;
}

export interface SearchResponse {
  results: SearchResult[];
  count: number;
}

export interface Tag {
  id: number;
  name: string;
  count: number;
}

export interface TagsResponse {
  tags: Tag[];
}

export interface Metadata {
  path: string;
  tags: string[];
  notes: string;
  urls: string[];
}

export interface ThumbnailBatchRequest {
  paths: string[];
  size?: number;
}

export interface ThumbnailBatchResponse {
  thumbnails: Record<string, string>;
}

export interface ShareLink {
  id: string;
  paths: string[];
  password?: string;
  has_password: boolean;
  expires_at?: string;
  max_downloads?: number;
  download_count: number;
  allow_preview: boolean;
  created_at: string;
  url: string;
  requires_key: boolean;
}

export interface ShareCreateRequest {
  paths: string[];
  password?: string;
  expires_hours?: number;
  max_downloads?: number;
  allow_preview?: boolean;
}

export interface ShareVerifyResponse {
  token: string;
  share: ShareLink;
}

export interface ShareInfoResponse {
  id: string;
  has_password: boolean;
  expired: boolean;
  allow_preview: boolean;
  paths?: string[];
  name?: string;
}

export interface StatsResponse {
  connections: number;
  requests: number;
  bytes_transferred: number;
  bytes_transferred_fmt: string;
  uptime: number;
}

export interface UsersResponse {
  users: User[];
}

export interface InviteCode {
  code: string;
  created_at: string;
  used_by?: string;
  revoked: boolean;
}

export interface InvitesResponse {
  invites: InviteCode[];
}

export interface ActivityLog {
  id: number;
  username: string;
  action: string;
  details: string;
  ip: string;
  timestamp: string;
}

export interface ActivityResponse {
  activities: ActivityLog[];
}

export interface OnlineUsersResponse {
  users: Array<{
    username: string;
    ip: string;
    connected_at: string;
  }>;
}

export interface ErrorResponse {
  error: string;
}

export interface OkResponse {
  ok: boolean;
}
```

**Step 2: 创建 src/api/client.ts**

webui/src/api/client.ts:
```typescript
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export interface ApiClientOptions {
  baseUrl?: string;
  getToken?: () => string | null;
  onUnauthorized?: () => void;
}

export function createApiClient(options: ApiClientOptions = {}) {
  const { baseUrl = '', getToken, onUnauthorized } = options;

  async function request<T>(
    method: HttpMethod,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | boolean | undefined | null>,
    signal?: AbortSignal,
  ): Promise<T> {
    const url = new URL(BASE + '/api/' + path, window.location.origin);

    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v != null && v !== '') {
          url.searchParams.set(k, String(v));
        }
      });
    }

    const headers: Record<string, string> = {};
    const token = getToken?.();
    if (token) {
      headers['Authorization'] = 'Bearer ' + token;
    }

    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url.toString(), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });

    if (response.status === 401) {
      onUnauthorized?.();
      throw new Error('Unauthorized');
    }

    if (response.status === 403) {
      throw new Error('Forbidden');
    }

    if (response.status === 429) {
      throw new Error('Rate limited');
    }

    if (!response.ok) {
      const errBody = await response.json().catch(() => ({}));
      throw new Error((errBody as { error?: string }).error ?? 'HTTP ' + response.status);
    }

    return response.json() as Promise<T>;
  }

  return {
    get: <T>(path: string, params?: Record<string, string | number | boolean | undefined | null>, signal?: AbortSignal) =>
      request<T>('GET', path, undefined, params, signal),
    post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
      request<T>('POST', path, body, undefined, signal),
    put: <T>(path: string, body?: unknown) =>
      request<T>('PUT', path, body),
    delete: <T>(path: string) =>
      request<T>('DELETE', path),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
```


---

## Task 3: 认证系统

**Covers:** [S7, S8]

**Files:**
- Create: `webui/src/api/auth.ts`
- Create: `webui/src/stores/AuthContext.tsx`
- Create: `webui/src/hooks/useAuth.ts`

**Interfaces:**
- Consumes: `src/api/client.ts` ApiClient, `src/types/api.ts` 认证类型
- Produces: `AuthProvider`, `useAuth` hook

**Step 1: 创建 src/api/auth.ts**

webui/src/api/auth.ts:
```typescript
import type { ApiClient } from './client';
import type { LoginResponse, RegisterResponse, MeResponse, OkResponse } from '../types/api';

export function createAuthApi(api: ApiClient) {
  return {
    login: (username: string, password: string) =>
      api.post<LoginResponse>('auth/login', { username, password }),
    loginWithPassword: (password: string) =>
      api.post<LoginResponse>('auth/login', { password }),
    register: (username: string, password: string, email?: string, invite_code?: string) =>
      api.post<RegisterResponse>('auth/register', { username, password, email, invite_code }),
    verifyKey: (key: string) =>
      api.post<LoginResponse>('auth/verify_key', { key }),
    logout: () =>
      api.post<OkResponse>('auth/logout'),
    me: () =>
      api.get<MeResponse>('auth/me'),
  };
}

export type AuthApi = ReturnType<typeof createAuthApi>;
```

**Step 2: 创建 src/stores/AuthContext.tsx**

webui/src/stores/AuthContext.tsx:
```typescript
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react';
import { createApiClient, type ApiClient } from '../api/client';
import { createAuthApi, type AuthApi } from '../api/auth';
import type { ServerInfo, User } from '../types/api';

export interface AuthState {
  token: string | null;
  user: User | null;
  role: 'admin' | 'user' | 'guest' | null;
  permissions: string[];
  isAuthenticated: boolean;
  isLoading: boolean;
  authMode: ServerInfo['auth_mode'];
  serverInfo: ServerInfo | null;
}

export interface AuthContextValue extends AuthState {
  api: ApiClient;
  authApi: AuthApi;
  setToken: (token: string | null, user?: User | null) => void;
  logout: () => void;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function getStoredToken(): string | null {
  return sessionStorage.getItem('lan_token');
}

function storeToken(token: string | null) {
  if (token) {
    sessionStorage.setItem('lan_token', token);
  } else {
    sessionStorage.removeItem('lan_token');
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getStoredToken);
  const [user, setUser] = useState<User | null>(null);
  const [role, setRole] = useState<AuthState['role']>(null);
  const [permissions, setPermissions] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [authMode, setAuthMode] = useState<ServerInfo['auth_mode']>('none');
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);

  const handleUnauthorized = useCallback(() => {
    setTokenState(null);
    storeToken(null);
    setUser(null);
    setRole('guest');
    setPermissions([]);
  }, []);

  const api = createApiClient({
    getToken: () => token,
    onUnauthorized: handleUnauthorized,
  });

  const authApi = createAuthApi(api);

  const setToken = useCallback((newToken: string | null, newUser?: User | null) => {
    setTokenState(newToken);
    storeToken(newToken);
    if (newToken) {
      setRole(newUser?.role === 'admin' ? 'admin' : 'user');
      setUser(newUser ?? null);
      setPermissions(newUser?.role === 'admin'
        ? ['browse', 'download', 'upload', 'manage_links', 'manage_users', 'settings', 'preview']
        : ['browse', 'download', 'preview']);
    } else {
      setUser(null);
      setRole('guest');
      setPermissions(['browse', 'preview']);
    }
  }, []);

  const logout = useCallback(() => {
    authApi.logout().catch(() => {});
    setToken(null);
  }, [authApi]);

  const refreshMe = useCallback(async () => {
    try {
      const res = await authApi.me();
      setUser(res.user);
      setRole(res.user.role === 'admin' ? 'admin' : 'user');
      setPermissions(res.user.role === 'admin'
        ? ['browse', 'download', 'upload', 'manage_links', 'manage_users', 'settings', 'preview']
        : ['browse', 'download', 'preview']);
    } catch {
      setUser(null);
      setRole('guest');
      setPermissions(['browse', 'preview']);
    }
  }, [authApi]);

  useEffect(() => {
    const init = async () => {
      try {
        const infoApi = createApiClient();
        const info = await infoApi.get<ServerInfo>('info');
        setServerInfo(info);
        setAuthMode(info.auth_mode);

        if (!info.auth_enabled) {
          setRole('guest');
          setPermissions(['browse', 'download', 'preview']);
          setIsLoading(false);
          return;
        }

        if (token) {
          await refreshMe();
        } else {
          setRole('guest');
          setPermissions(['browse', 'preview']);
        }
      } catch {
        // Server unreachable
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const value: AuthContextValue = {
    token, user, role, permissions,
    isAuthenticated: !!token && (role === 'admin' || role === 'user'),
    isLoading, authMode, serverInfo, api, authApi,
    setToken, logout, refreshMe,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuthContext must be used within AuthProvider');
  return ctx;
}
```

**Step 3: 创建 src/hooks/useAuth.ts**

webui/src/hooks/useAuth.ts:
```typescript
export { useAuthContext as useAuth } from '../stores/AuthContext';
```

**Step 4: 更新 App.tsx 集成 AuthProvider**

webui/src/App.tsx:
```typescript
import { AuthProvider } from './stores/AuthContext';

function App() {
  return (
    <AuthProvider>
      <div className="flex items-center justify-center h-screen">
        <h1 className="text-2xl font-semibold text-slate-300">AssetManager WebUI</h1>
      </div>
    </AuthProvider>
  );
}

export default App;
```


---

## Task 4: 路由框架 + 基础页面

**Covers:** [S4, S5]

**Files:**
- Create: `webui/src/pages/LandingPage.tsx`
- Create: `webui/src/pages/LoginPage.tsx`
- Create: `webui/src/pages/BrowsePage.tsx`
- Create: `webui/src/pages/DetailPage.tsx`
- Create: `webui/src/pages/ShareReceivePage.tsx`
- Modify: `webui/src/App.tsx`

**Step 1: 创建 LandingPage.tsx**

webui/src/pages/LandingPage.tsx:
```typescript
import { useAuth } from '../hooks/useAuth';

export default function LandingPage() {
  const { serverInfo, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="skeleton h-8 w-48" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center h-screen gap-6 p-8">
      <h1 className="text-4xl font-bold text-white">
        {serverInfo?.share_name ?? 'AssetManager'}
      </h1>
      <p className="text-slate-400 text-lg text-center max-w-md">
        {serverInfo?.welcome_msg ?? 'Browse and download files from your asset library.'}
      </p>
      <div className="flex gap-4 mt-4">
        <a href="/browse" className="px-6 py-3 bg-brand-500 hover:bg-brand-600 text-white rounded-lg font-medium transition-colors">
          Enter Library
        </a>
      </div>
    </div>
  );
}
```

**Step 2: 创建 LoginPage.tsx**

webui/src/pages/LoginPage.tsx:
```typescript
export default function LoginPage() {
  return (
    <div className="flex items-center justify-center h-screen">
      <div className="w-full max-w-sm p-6 rounded-xl bg-slate-900 border border-slate-700/50">
        <h2 className="text-xl font-semibold text-white mb-6">Login</h2>
        <p className="text-slate-400">Login form coming soon.</p>
      </div>
    </div>
  );
}
```

**Step 3: 创建 BrowsePage.tsx**

webui/src/pages/BrowsePage.tsx:
```typescript
export default function BrowsePage() {
  return (
    <div className="flex items-center justify-center h-screen">
      <p className="text-slate-400">Browse page coming soon.</p>
    </div>
  );
}
```

**Step 4: 创建 DetailPage.tsx**

webui/src/pages/DetailPage.tsx:
```typescript
export default function DetailPage() {
  return (
    <div className="flex items-center justify-center h-screen">
      <p className="text-slate-400">Detail page coming soon.</p>
    </div>
  );
}
```

**Step 5: 创建 ShareReceivePage.tsx**

webui/src/pages/ShareReceivePage.tsx:
```typescript
import { useParams } from 'react-router-dom';

export default function ShareReceivePage() {
  const { shareId } = useParams<{ shareId: string }>();
  return (
    <div className="flex flex-col items-center justify-center h-screen gap-4 p-8">
      <h1 className="text-2xl font-semibold text-white">Shared Files</h1>
      <p className="text-slate-400">Share ID: {shareId}</p>
    </div>
  );
}
```

**Step 6: 更新 App.tsx 集成路由**

webui/src/App.tsx:
```typescript
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './stores/AuthContext';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import BrowsePage from './pages/BrowsePage';
import DetailPage from './pages/DetailPage';
import ShareReceivePage from './pages/ShareReceivePage';

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/browse" element={<BrowsePage />} />
          <Route path="/detail" element={<DetailPage />} />
          <Route path="/s/:shareId" element={<ShareReceivePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
```


---

## Task 5: i18n 国际化模块

**Covers:** [S3, S9]

**Files:**
- Create: `webui/src/i18n/index.ts`
- Create: `webui/src/i18n/en.ts`
- Create: `webui/src/i18n/zh.ts`
- Create: `webui/src/i18n/ja.ts`
- Create: `webui/src/hooks/useI18n.ts`

**Interfaces:**
- Produces: `useI18n()` hook 返回 `{ t, lang, setLang, supportedLangs }`

**Step 1: 创建英文翻译字典**

webui/src/i18n/en.ts:
```typescript
const en = {
  app: { name: 'AssetManager', loading: 'Loading...', error: 'An error occurred', retry: 'Retry', cancel: 'Cancel', confirm: 'Confirm', save: 'Save', delete: 'Delete', close: 'Close', back: 'Back', search: 'Search', noResults: 'No results found', all: 'All', none: 'None', yes: 'Yes', no: 'No' },
  landing: { welcome: 'Welcome', enterLibrary: 'Enter Library', serverInfo: 'Server Info', version: 'Version', libraryStats: 'Library Stats', totalProjects: 'Total Projects', totalSize: 'Total Size', authRequired: 'Authentication Required', loginPrompt: 'Please log in to access the library' },
  header: { home: 'Home', browse: 'Browse', admin: 'Admin', login: 'Login', logout: 'Logout', register: 'Register', profile: 'Profile', settings: 'Settings', language: 'Language', theme: 'Theme', dark: 'Dark', light: 'Light', searchPlaceholder: 'Search files and folders...', userMenu: 'User menu' },
  sidebar: { library: 'Library', toggle: 'Toggle sidebar', collapse: 'Collapse sidebar', expand: 'Expand sidebar', noTree: 'No directory tree available', loadingTree: 'Loading directory tree...', filterPlaceholder: 'Filter directories...', noMatches: 'No matching directories' },
  browse: { title: 'Browse', empty: 'This folder is empty', loading: 'Loading files...', error: 'Failed to load files', selected: '{0} item(s) selected', selectAll: 'Select all', deselectAll: 'Deselect all', uploading: 'Uploading...', uploadSuccess: 'Upload successful', uploadFailed: 'Upload failed', downloadSelected: 'Download selected', shareSelected: 'Share selected', deleteSelected: 'Delete selected', confirmDelete: 'Are you sure you want to delete {0} item(s)?', newFolder: 'New Folder', newFolderPrompt: 'Enter folder name:', rename: 'Rename', renamePrompt: 'Enter new name:' },
  sort: { label: 'Sort by', name: 'Name', size: 'Size', modified: 'Modified', type: 'Type', asc: 'Ascending', desc: 'Descending' },
  view: { grid: 'Grid view', list: 'List view', compact: 'Compact view' },
  info: { panel: 'Info', noSelection: 'No item selected', details: 'Details', name: 'Name', path: 'Path', size: 'Size', modified: 'Modified', type: 'Type', extension: 'Extension', category: 'Category', tags: 'Tags', notes: 'Notes', urls: 'URLs', addTag: 'Add tag', addNote: 'Add note', addUrl: 'Add URL', editNote: 'Edit note', editUrls: 'Edit URLs', saveMetadata: 'Save metadata', metadataSaved: 'Metadata saved', metadataFailed: 'Failed to save metadata' },
  action: { download: 'Download', preview: 'Preview', open: 'Open', share: 'Share', copy: 'Copy', cut: 'Cut', paste: 'Paste', rename: 'Rename', move: 'Move', delete: 'Delete', properties: 'Properties', refresh: 'Refresh' },
  auth: { loginTitle: 'Login', registerTitle: 'Register', username: 'Username', password: 'Password', confirmPassword: 'Confirm Password', email: 'Email', loginButton: 'Login', registerButton: 'Register', loginFailed: 'Login failed', registerFailed: 'Registration failed', loginSuccess: 'Login successful', registerSuccess: 'Registration successful', loggedOut: 'Logged out', sessionExpired: 'Session expired, please log in again', noAccount: "Don't have an account?", hasAccount: 'Already have an account?', registerLink: 'Register here', loginLink: 'Login here', passwordMode: 'Enter password to access', keyMode: 'Enter access key', keyPlaceholder: 'Access key', verify: 'Verify', inviteCode: 'Invite Code', invitePlaceholder: 'Invite code (if required)', loggingIn: 'Logging in...' },
  share: { title: 'Share Files', createLink: 'Create Share Link', manageLinks: 'Manage Share Links', noLinks: 'No share links', linkCreated: 'Share link created', linkDeleted: 'Share link deleted', createFailed: 'Failed to create share link', deleteFailed: 'Failed to delete share link', password: 'Password (optional)', expiresIn: 'Expires in', hours: 'hours', maxDownloads: 'Max downloads', unlimited: 'Unlimited', allowPreview: 'Allow preview', copyLink: 'Copy link', linkCopied: 'Link copied to clipboard', deleteConfirm: 'Delete this share link?', passwordRequired: 'This share requires a password', verifyPassword: 'Verify Password', wrongPassword: 'Wrong password', expired: 'This share has expired', download: 'Download', downloadAll: 'Download all', preview: 'Preview', details: 'Share details', sharedBy: 'Shared by', createdAt: 'Created', downloadCount: 'Downloads', maxDownloadsReached: 'Maximum downloads reached', requiresKey: 'Requires access key', verifyKey: 'Verify Access Key' },
  detail: { title: 'Details', overview: 'Overview', files: 'Files', images: 'Images', noImages: 'No images', noFiles: 'No files in this project', totalItems: 'Total items', itemCount: '{0} item(s)', openInBrowser: 'Open in browser' },
  viewer: { title: 'Image Viewer', zoomIn: 'Zoom in', zoomOut: 'Zoom out', zoomReset: 'Reset zoom', fitToScreen: 'Fit to screen', previous: 'Previous', next: 'Next', close: 'Close (Esc)', imageCount: '{0} of {1}', loading: 'Loading image...', loadError: 'Failed to load image' },
  status: { online: 'Online', offline: 'Offline', connecting: 'Connecting...', connected: 'Connected', disconnected: 'Disconnected', reconnecting: 'Reconnecting...' },
  error: { generic: 'Something went wrong', notFound: 'Page not found', forbidden: 'Access denied', unauthorized: 'Please log in', serverError: 'Server error', networkError: 'Network error', timeout: 'Request timed out', rateLimited: 'Too many requests, please slow down', uploadTooLarge: 'File too large', unsupportedType: 'Unsupported file type' },
  perm: { noPermission: 'You do not have permission to perform this action', adminOnly: 'This action requires admin privileges', loginRequired: 'Please log in to perform this action' },
  mobile: { menu: 'Menu', search: 'Search', filter: 'Filter', sort: 'Sort', actions: 'Actions', info: 'Info' },
  admin: { title: 'Admin Panel', users: 'User Management', invites: 'Invite Codes', shares: 'Share Management', activity: 'Activity Log', online: 'Online Users', stats: 'Server Stats', createInvite: 'Create Invite', revokeInvite: 'Revoke', noInvites: 'No invite codes', noActivity: 'No recent activity', noOnlineUsers: 'No users online', userRole: 'Role', userStatus: 'Status', active: 'Active', inactive: 'Inactive', deactivateUser: 'Deactivate user', activateUser: 'Activate user', confirmDeactivate: 'Deactivate this user?', deleteUser: 'Delete user', confirmDeleteUser: 'Delete this user permanently?', username: 'Username', role: 'Role', lastLogin: 'Last login', joined: 'Joined', createdAt: 'Created', usedBy: 'Used by', revoked: 'Revoked', action: 'Action', details: 'Details', ip: 'IP', timestamp: 'Timestamp' },
  theme: { title: 'Theme', dark: 'Dark Mode', light: 'Light Mode', system: 'System', color: 'Accent Color' },
};
export default en;
export type I18nDict = typeof en;
```

**Step 2: 创建中文翻译**

webui/src/i18n/zh.ts:
```typescript
import type { I18nDict } from './en';
const zh: I18nDict = {
  app: { name: '资产管理器', loading: '加载中...', error: '发生错误', retry: '重试', cancel: '取消', confirm: '确认', save: '保存', delete: '删除', close: '关闭', back: '返回', search: '搜索', noResults: '未找到结果', all: '全部', none: '无', yes: '是', no: '否' },
  landing: { welcome: '欢迎', enterLibrary: '进入库', serverInfo: '服务器信息', version: '版本', libraryStats: '库状态', totalProjects: '项目总数', totalSize: '总大小', authRequired: '需要认证', loginPrompt: '请登录以访问库' },
  header: { home: '首页', browse: '浏览', admin: '管理', login: '登录', logout: '退出', register: '注册', profile: '个人资料', settings: '设置', language: '语言', theme: '主题', dark: '深色', light: '浅色', searchPlaceholder: '搜索文件和文件夹...', userMenu: '用户菜单' },
  sidebar: { library: '库', toggle: '切换侧边栏', collapse: '收起侧边栏', expand: '展开侧边栏', noTree: '无法获取目录树', loadingTree: '加载目录树中...', filterPlaceholder: '过滤目录...', noMatches: '没有匹配的目录' },
  browse: { title: '浏览', empty: '此文件夹为空', loading: '加载文件中...', error: '加载文件失败', selected: '已选择 {0} 项', selectAll: '全选', deselectAll: '取消全选', uploading: '上传中...', uploadSuccess: '上传成功', uploadFailed: '上传失败', downloadSelected: '下载选中', shareSelected: '分享选中', deleteSelected: '删除选中', confirmDelete: '确定要删除 {0} 项吗？', newFolder: '新建文件夹', newFolderPrompt: '输入文件夹名称：', rename: '重命名', renamePrompt: '输入新名称：' },
  sort: { label: '排序', name: '名称', size: '大小', modified: '修改时间', type: '类型', asc: '升序', desc: '降序' },
  view: { grid: '网格视图', list: '列表视图', compact: '紧凑视图' },
  info: { panel: '信息', noSelection: '未选择项目', details: '详情', name: '名称', path: '路径', size: '大小', modified: '修改时间', type: '类型', extension: '扩展名', category: '分类', tags: '标签', notes: '备注', urls: 'URL', addTag: '添加标签', addNote: '添加备注', addUrl: '添加链接', editNote: '编辑备注', editUrls: '编辑链接', saveMetadata: '保存元数据', metadataSaved: '元数据已保存', metadataFailed: '保存元数据失败' },
  action: { download: '下载', preview: '预览', open: '打开', share: '分享', copy: '复制', cut: '剪切', paste: '粘贴', rename: '重命名', move: '移动', delete: '删除', properties: '属性', refresh: '刷新' },
  auth: { loginTitle: '登录', registerTitle: '注册', username: '用户名', password: '密码', confirmPassword: '确认密码', email: '邮箱', loginButton: '登录', registerButton: '注册', loginFailed: '登录失败', registerFailed: '注册失败', loginSuccess: '登录成功', registerSuccess: '注册成功', loggedOut: '已退出登录', sessionExpired: '会话已过期，请重新登录', noAccount: '没有账号？', hasAccount: '已有账号？', registerLink: '在此注册', loginLink: '在此登录', passwordMode: '输入密码以访问', keyMode: '输入访问密钥', keyPlaceholder: '访问密钥', verify: '验证', inviteCode: '邀请码', invitePlaceholder: '邀请码（如需要）', loggingIn: '登录中...' },
  share: { title: '分享文件', createLink: '创建分享链接', manageLinks: '管理分享链接', noLinks: '暂无分享链接', linkCreated: '分享链接已创建', linkDeleted: '分享链接已删除', createFailed: '创建分享链接失败', deleteFailed: '删除分享链接失败', password: '密码（可选）', expiresIn: '有效期', hours: '小时', maxDownloads: '最大下载次数', unlimited: '不限', allowPreview: '允许预览', copyLink: '复制链接', linkCopied: '链接已复制到剪贴板', deleteConfirm: '确定删除此分享链接？', passwordRequired: '此分享需要密码', verifyPassword: '验证密码', wrongPassword: '密码错误', expired: '此分享已过期', download: '下载', downloadAll: '下载全部', preview: '预览', details: '分享详情', sharedBy: '分享者', createdAt: '创建时间', downloadCount: '下载次数', maxDownloadsReached: '已达到最大下载次数', requiresKey: '需要访问密钥', verifyKey: '验证访问密钥' },
  detail: { title: '详情', overview: '概览', files: '文件', images: '图片', noImages: '无图片', noFiles: '此项目中无文件', totalItems: '项目总数', itemCount: '{0} 项', openInBrowser: '在浏览器中打开' },
  viewer: { title: '图片查看器', zoomIn: '放大', zoomOut: '缩小', zoomReset: '重置缩放', fitToScreen: '适应屏幕', previous: '上一张', next: '下一张', close: '关闭 (Esc)', imageCount: '{0} / {1}', loading: '加载图片中...', loadError: '加载图片失败' },
  status: { online: '在线', offline: '离线', connecting: '连接中...', connected: '已连接', disconnected: '已断开', reconnecting: '重新连接中...' },
  error: { generic: '出了点问题', notFound: '页面未找到', forbidden: '访问被拒绝', unauthorized: '请先登录', serverError: '服务器错误', networkError: '网络错误', timeout: '请求超时', rateLimited: '请求过于频繁，请稍后再试', uploadTooLarge: '文件过大', unsupportedType: '不支持的文件类型' },
  perm: { noPermission: '您没有权限执行此操作', adminOnly: '此操作需要管理员权限', loginRequired: '请登录以执行此操作' },
  mobile: { menu: '菜单', search: '搜索', filter: '筛选', sort: '排序', actions: '操作', info: '信息' },
  admin: { title: '管理面板', users: '用户管理', invites: '邀请码', shares: '分享管理', activity: '活动日志', online: '在线用户', stats: '服务器状态', createInvite: '创建邀请码', revokeInvite: '撤销', noInvites: '暂无邀请码', noActivity: '暂无近期活动', noOnlineUsers: '没有用户在线', userRole: '角色', userStatus: '状态', active: '活跃', inactive: '停用', deactivateUser: '停用用户', activateUser: '启用用户', confirmDeactivate: '确定停用此用户？', deleteUser: '删除用户', confirmDeleteUser: '确定永久删除此用户？', username: '用户名', role: '角色', lastLogin: '上次登录', joined: '注册时间', createdAt: '创建时间', usedBy: '使用者', revoked: '已撤销', action: '操作', details: '详情', ip: 'IP', timestamp: '时间' },
  theme: { title: '主题', dark: '深色模式', light: '浅色模式', system: '跟随系统', color: '强调色' },
};
export default zh;
```

**Step 3: 创建日文翻译**

webui/src/i18n/ja.ts:
```typescript
import type { I18nDict } from './en';
const ja: I18nDict = {
  app: { name: 'アセットマネージャー', loading: '読み込み中...', error: 'エラーが発生しました', retry: '再試行', cancel: 'キャンセル', confirm: '確認', save: '保存', delete: '削除', close: '閉じる', back: '戻る', search: '検索', noResults: '結果が見つかりません', all: 'すべて', none: 'なし', yes: 'はい', no: 'いいえ' },
  landing: { welcome: 'ようこそ', enterLibrary: 'ライブラリに入る', serverInfo: 'サーバー情報', version: 'バージョン', libraryStats: 'ライブラリ統計', totalProjects: '総プロジェクト数', totalSize: '総サイズ', authRequired: '認証が必要です', loginPrompt: 'ライブラリにアクセスするにはログインしてください' },
  header: { home: 'ホーム', browse: 'ブラウズ', admin: '管理', login: 'ログイン', logout: 'ログアウト', register: '登録', profile: 'プロフィール', settings: '設定', language: '言語', theme: 'テーマ', dark: 'ダーク', light: 'ライト', searchPlaceholder: 'ファイルとフォルダを検索...', userMenu: 'ユーザーメニュー' },
  sidebar: { library: 'ライブラリ', toggle: 'サイドバー切替', collapse: 'サイドバーを閉じる', expand: 'サイドバーを開く', noTree: 'ディレクトリツリーがありません', loadingTree: 'ディレクトリツリーを読み込み中...', filterPlaceholder: 'ディレクトリをフィルター...', noMatches: '一致するディレクトリがありません' },
  browse: { title: 'ブラウズ', empty: 'このフォルダは空です', loading: 'ファイルを読み込み中...', error: 'ファイルの読み込みに失敗しました', selected: '{0} 個の項目を選択中', selectAll: 'すべて選択', deselectAll: '選択解除', uploading: 'アップロード中...', uploadSuccess: 'アップロード成功', uploadFailed: 'アップロード失敗', downloadSelected: '選択項目をダウンロード', shareSelected: '選択項目を共有', deleteSelected: '選択項目を削除', confirmDelete: '{0} 個の項目を削除してもよろしいですか？', newFolder: '新規フォルダ', newFolderPrompt: 'フォルダ名を入力：', rename: '名前変更', renamePrompt: '新しい名前を入力：' },
  sort: { label: '並び替え', name: '名前', size: 'サイズ', modified: '更新日', type: '種類', asc: '昇順', desc: '降順' },
  view: { grid: 'グリッド表示', list: 'リスト表示', compact: 'コンパクト表示' },
  info: { panel: '情報', noSelection: '項目が選択されていません', details: '詳細', name: '名前', path: 'パス', size: 'サイズ', modified: '更新日', type: '種類', extension: '拡張子', category: 'カテゴリ', tags: 'タグ', notes: 'メモ', urls: 'URL', addTag: 'タグを追加', addNote: 'メモを追加', addUrl: 'URLを追加', editNote: 'メモを編集', editUrls: 'URLを編集', saveMetadata: 'メタデータを保存', metadataSaved: 'メタデータを保存しました', metadataFailed: 'メタデータの保存に失敗しました' },
  action: { download: 'ダウンロード', preview: 'プレビュー', open: '開く', share: '共有', copy: 'コピー', cut: 'カット', paste: 'ペースト', rename: '名前変更', move: '移動', delete: '削除', properties: 'プロパティ', refresh: '更新' },
  auth: { loginTitle: 'ログイン', registerTitle: '登録', username: 'ユーザー名', password: 'パスワード', confirmPassword: 'パスワード確認', email: 'メール', loginButton: 'ログイン', registerButton: '登録', loginFailed: 'ログインに失敗しました', registerFailed: '登録に失敗しました', loginSuccess: 'ログイン成功', registerSuccess: '登録成功', loggedOut: 'ログアウトしました', sessionExpired: 'セッションの有効期限が切れました。再ログインしてください', noAccount: 'アカウントがありませんか？', hasAccount: 'すでにアカウントをお持ちですか？', registerLink: 'こちらから登録', loginLink: 'こちらからログイン', passwordMode: 'パスワードを入力してアクセス', keyMode: 'アクセスキーを入力', keyPlaceholder: 'アクセスキー', verify: '確認', inviteCode: '招待コード', invitePlaceholder: '招待コード（必要な場合）', loggingIn: 'ログイン中...' },
  share: { title: 'ファイルを共有', createLink: '共有リンクを作成', manageLinks: '共有リンクを管理', noLinks: '共有リンクがありません', linkCreated: '共有リンクを作成しました', linkDeleted: '共有リンクを削除しました', createFailed: '共有リンクの作成に失敗しました', deleteFailed: '共有リンクの削除に失敗しました', password: 'パスワード（オプション）', expiresIn: '有効期限', hours: '時間', maxDownloads: '最大ダウンロード数', unlimited: '無制限', allowPreview: 'プレビューを許可', copyLink: 'リンクをコピー', linkCopied: 'リンクをクリップボードにコピーしました', deleteConfirm: 'この共有リンクを削除しますか？', passwordRequired: 'この共有にはパスワードが必要です', verifyPassword: 'パスワード確認', wrongPassword: 'パスワードが間違っています', expired: 'この共有は期限切れです', download: 'ダウンロード', downloadAll: 'すべてダウンロード', preview: 'プレビュー', details: '共有詳細', sharedBy: '共有者', createdAt: '作成日時', downloadCount: 'ダウンロード数', maxDownloadsReached: '最大ダウンロード数に達しました', requiresKey: 'アクセスキーが必要です', verifyKey: 'アクセスキー確認' },
  detail: { title: '詳細', overview: '概要', files: 'ファイル', images: '画像', noImages: '画像がありません', noFiles: 'このプロジェクトにファイルはありません', totalItems: '総アイテム数', itemCount: '{0} 個のアイテム', openInBrowser: 'ブラウザで開く' },
  viewer: { title: '画像ビューア', zoomIn: '拡大', zoomOut: '縮小', zoomReset: 'ズームリセット', fitToScreen: '画面に合わせる', previous: '前へ', next: '次へ', close: '閉じる (Esc)', imageCount: '{0} / {1}', loading: '画像を読み込み中...', loadError: '画像の読み込みに失敗しました' },
  status: { online: 'オンライン', offline: 'オフライン', connecting: '接続中...', connected: '接続済み', disconnected: '切断されました', reconnecting: '再接続中...' },
  error: { generic: '問題が発生しました', notFound: 'ページが見つかりません', forbidden: 'アクセスが拒否されました', unauthorized: 'ログインしてください', serverError: 'サーバーエラー', networkError: 'ネットワークエラー', timeout: 'リクエストがタイムアウトしました', rateLimited: 'リクエストが多すぎます。しばらくお待ちください', uploadTooLarge: 'ファイルが大きすぎます', unsupportedType: 'サポートされていないファイル形式です' },
  perm: { noPermission: 'この操作を実行する権限がありません', adminOnly: 'この操作は管理者権限が必要です', loginRequired: 'この操作を実行するにはログインしてください' },
  mobile: { menu: 'メニュー', search: '検索', filter: 'フィルター', sort: '並び替え', actions: '操作', info: '情報' },
  admin: { title: '管理パネル', users: 'ユーザー管理', invites: '招待コード', shares: '共有管理', activity: 'アクティビティログ', online: 'オンラインユーザー', stats: 'サーバー統計', createInvite: '招待コードを作成', revokeInvite: '取り消し', noInvites: '招待コードがありません', noActivity: '最近のアクティビティはありません', noOnlineUsers: 'オンラインのユーザーはいません', userRole: '役割', userStatus: 'ステータス', active: 'アクティブ', inactive: '非アクティブ', deactivateUser: 'ユーザーを無効化', activateUser: 'ユーザーを有効化', confirmDeactivate: 'このユーザーを無効化しますか？', deleteUser: 'ユーザーを削除', confirmDeleteUser: 'このユーザーを完全に削除しますか？', username: 'ユーザー名', role: '役割', lastLogin: '最終ログイン', joined: '登録日', createdAt: '作成日時', usedBy: '使用者', revoked: '取り消し済み', action: '操作', details: '詳細', ip: 'IP', timestamp: '日時' },
  theme: { title: 'テーマ', dark: 'ダークモード', light: 'ライトモード', system: 'システム', color: 'アクセントカラー' },
};
export default ja;
```

**Step 4: 创建 i18n 核心模块**

webui/src/i18n/index.ts:
```typescript
import en from './en';
import zh from './zh';
import ja from './ja';
import type { I18nDict } from './en';

const dictionaries: Record<string, I18nDict> = { en, zh, ja };
const SUPPORTED_LANGS = ['en', 'zh', 'ja'] as const;
type Lang = (typeof SUPPORTED_LANGS)[number];

function detectLang(): Lang {
  const stored = localStorage.getItem('am_lang');
  if (stored && SUPPORTED_LANGS.includes(stored as Lang)) return stored as Lang;
  const browserLang = navigator.language.slice(0, 2);
  if (SUPPORTED_LANGS.includes(browserLang as Lang)) return browserLang as Lang;
  return 'en';
}

let currentLang: Lang = detectLang();
let currentDict: I18nDict = dictionaries[currentLang] ?? en;

export function t(key: string, ...args: (string | number)[]): string {
  const keys = key.split('.');
  let value: any = currentDict;
  for (const k of keys) {
    value = value?.[k];
    if (value === undefined) return key;
  }
  if (typeof value === 'string') {
    return args.reduce((str, arg, i) => str.replace('{' + i + '}', String(arg)), value);
  }
  return key;
}

export function setLang(lang: Lang): void {
  currentLang = lang;
  currentDict = dictionaries[lang] ?? en;
  localStorage.setItem('am_lang', lang);
}

export function getLang(): Lang {
  return currentLang;
}

export type { Lang };
export { SUPPORTED_LANGS };
```

**Step 5: 创建 useI18n hook**

webui/src/hooks/useI18n.ts:
```typescript
import { useState, useCallback } from 'react';
import { t, setLang, getLang, type Lang, SUPPORTED_LANGS } from '../i18n';

export function useI18n() {
  const [lang, setLangState] = useState<Lang>(getLang());
  const changeLang = useCallback((newLang: Lang) => {
    setLang(newLang);
    setLangState(newLang);
  }, []);
  return { t, lang, setLang: changeLang, supportedLangs: SUPPORTED_LANGS };
}
```


---

## Task 6: 通用 UI 组件

**Covers:** [S6, S9]

**Files:**
- Create: `webui/src/components/ui/Toast.tsx`
- Create: `webui/src/components/ui/Skeleton.tsx`
- Create: `webui/src/components/ui/Modal.tsx`
- Create: `webui/src/components/ui/ContextMenu.tsx`

**Step 1: 创建 Toast 组件**

webui/src/components/ui/Toast.tsx:
```typescript
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import { X } from 'lucide-react';

type ToastType = 'success' | 'error' | 'info';

interface Toast {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastContextValue {
  toast: (type: ToastType, message: string) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);
let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const removeToast = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);
  const addToast = useCallback((type: ToastType, message: string) => {
    const id = nextId++;
    setToasts(prev => [...prev, { id, type, message }]);
    setTimeout(() => removeToast(id), 4000);
  }, [removeToast]);

  const value: ToastContextValue = {
    toast: addToast,
    success: (msg: string) => addToast('success', msg),
    error: (msg: string) => addToast('error', msg),
    info: (msg: string) => addToast('info', msg),
  };

  const typeStyles: Record<ToastType, string> = {
    success: 'bg-green-600/90 border-green-500',
    error: 'bg-red-600/90 border-red-500',
    info: 'bg-brand-600/90 border-brand-500',
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map(t => (
          <div key={t.id} className={'flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg text-white text-sm animate-slide-up ' + typeStyles[t.type]}>
            <span className="flex-1">{t.message}</span>
            <button onClick={() => removeToast(t.id)} className="text-white/70 hover:text-white">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
```

**Step 2: 创建 Skeleton 组件**

webui/src/components/ui/Skeleton.tsx:
```typescript
interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = '' }: SkeletonProps) {
  return <div className={'skeleton ' + className} />;
}

export function CardSkeleton() {
  return (
    <div className="rounded-xl bg-slate-900 border border-slate-700/50 overflow-hidden">
      <Skeleton className="aspect-video rounded-none" />
      <div className="p-3 space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </div>
  );
}
```

**Step 3: 创建 Modal 组件**

webui/src/components/ui/Modal.tsx:
```typescript
import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  className?: string;
}

export function Modal({ open, onClose, title, children, className = '' }: ModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
    >
      <div className={'bg-slate-900 border border-slate-700/50 rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto ' + className}>
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50">
            <h3 className="text-lg font-semibold text-white">{title}</h3>
            <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>
        )}
        <div className="p-6">{children}</div>
      </div>
    </div>
  );
}
```

**Step 4: 创建 ContextMenu 组件**

webui/src/components/ui/ContextMenu.tsx:
```typescript
import { useEffect, useRef } from 'react';
import type { LucideIcon } from 'lucide-react';

interface MenuItem {
  label: string;
  icon?: LucideIcon;
  onClick: () => void;
  disabled?: boolean;
  divider?: boolean;
}

interface ContextMenuProps {
  x: number;
  y: number;
  items: MenuItem[];
  onClose: () => void;
}

export function ContextMenu({ x, y, items, onClose }: ContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-50 min-w-[160px] bg-slate-800 border border-slate-700/50 rounded-lg shadow-xl py-1"
      style={{ left: x, top: y }}
    >
      {items.map((item, i) => (
        item.divider ? (
          <div key={i} className="my-1 border-t border-slate-700/50" />
        ) : (
          <button
            key={i}
            disabled={item.disabled}
            onClick={() => { item.onClick(); onClose(); }}
            className={'w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors ' +
              (item.disabled ? 'text-slate-600 cursor-not-allowed' : 'text-slate-200 hover:bg-slate-700/50')}
          >
            {item.icon && <item.icon size={14} />}
            {item.label}
          </button>
        )
      ))}
    </div>
  );
}
```


---

## Task 7: 布局组件 - Header + Sidebar + InfoPanel + AppLayout

**Covers:** [S5, S6]

**Files:**
- Create: `webui/src/components/layout/AppLayout.tsx`
- Create: `webui/src/components/layout/Header.tsx`
- Create: `webui/src/components/layout/Sidebar.tsx`
- Create: `webui/src/components/layout/InfoPanel.tsx`
- Create: `webui/src/components/layout/ResizablePanel.tsx`

**Step 1: 创建 AppLayout 组件**

webui/src/components/layout/AppLayout.tsx:
```typescript
import { useState, type ReactNode } from 'react';
import Header from './Header';
import Sidebar from './Sidebar';
import InfoPanel from './InfoPanel';

interface AppLayoutProps {
  children: ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [infoOpen, setInfoOpen] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="h-screen flex flex-col bg-slate-950">
      <Header onMenuClick={() => setMobileSidebarOpen(true)} onInfoToggle={() => setInfoOpen(prev => !prev)} />
      <div className="flex flex-1 overflow-hidden">
        <aside className={'hidden lg:flex flex-col border-r border-slate-700/50 transition-all duration-200 ' + (sidebarOpen ? 'w-60' : 'w-0 overflow-hidden')}>
          <Sidebar />
        </aside>
        {mobileSidebarOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-black/50" onClick={() => setMobileSidebarOpen(false)} />
            <aside className="relative w-72 h-full bg-slate-900 border-r border-slate-700/50 overflow-y-auto">
              <Sidebar />
            </aside>
          </div>
        )}
        <main className="flex-1 overflow-y-auto">{children}</main>
        {infoOpen && (
          <aside className="w-72 border-l border-slate-700/50 overflow-y-auto hidden xl:block">
            <InfoPanel onClose={() => setInfoOpen(false)} />
          </aside>
        )}
      </div>
    </div>
  );
}
```

**Step 2: 创建 Header 组件**

webui/src/components/layout/Header.tsx:
```typescript
import { Menu, Info, Search, Sun, Moon, LogOut, User, Globe } from 'lucide-react';
import { useAuth } from '../../hooks/useAuth';
import { useI18n } from '../../hooks/useI18n';
import { useTheme } from '../../hooks/useTheme';

interface HeaderProps {
  onMenuClick: () => void;
  onInfoToggle: () => void;
}

export default function Header({ onMenuClick, onInfoToggle }: HeaderProps) {
  const { user, role, logout, isAuthenticated, serverInfo } = useAuth();
  const { t, lang, setLang, supportedLangs } = useI18n();
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="h-14 flex items-center gap-3 px-4 border-b border-slate-700/50 bg-slate-900/50 backdrop-blur-sm shrink-0">
      <button onClick={onMenuClick} className="lg:hidden text-slate-400 hover:text-white p-1">
        <Menu size={20} />
      </button>
      <h1 className="font-semibold text-white text-sm truncate hidden sm:block">
        {serverInfo?.share_name ?? 'AssetManager'}
      </h1>
      <div className="flex-1 max-w-md mx-auto relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input type="text" placeholder={t('header.searchPlaceholder')}
          className="w-full h-9 pl-9 pr-3 rounded-lg bg-slate-800/50 border border-slate-700/50 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors" />
      </div>
      <div className="flex items-center gap-1">
        <div className="relative group">
          <button className="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-800/50 transition-colors">
            <Globe size={16} />
          </button>
          <div className="absolute right-0 top-full mt-1 bg-slate-800 border border-slate-700/50 rounded-lg shadow-xl py-1 hidden group-hover:block min-w-[100px]">
            {supportedLangs.map(l => (
              <button key={l} onClick={() => setLang(l)}
                className={'w-full text-left px-3 py-1.5 text-sm transition-colors ' + (lang === l ? 'text-brand-400 bg-slate-700/30' : 'text-slate-300 hover:bg-slate-700/50')}>
                {l === 'en' ? 'English' : l === 'zh' ? '中文' : '日本語'}
              </button>
            ))}
          </div>
        </div>
        <button onClick={toggleTheme} className="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-800/50 transition-colors">
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button onClick={onInfoToggle} className="text-slate-400 hover:text-white p-2 rounded-lg hover:bg-slate-800/50 transition-colors hidden xl:block">
          <Info size={16} />
        </button>
        {isAuthenticated ? (
          <div className="relative group">
            <button className="flex items-center gap-2 text-slate-300 hover:text-white px-2 py-1.5 rounded-lg hover:bg-slate-800/50 transition-colors text-sm">
              <User size={16} />
              <span className="hidden sm:inline">{user?.username}</span>
            </button>
            <div className="absolute right-0 top-full mt-1 bg-slate-800 border border-slate-700/50 rounded-lg shadow-xl py-1 hidden group-hover:block min-w-[140px]">
              {role === 'admin' && (
                <a href="/admin" className="block px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors">{t('header.admin')}</a>
              )}
              <button onClick={logout} className="w-full text-left px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-700/50 transition-colors flex items-center gap-2">
                <LogOut size={14} /> {t('header.logout')}
              </button>
            </div>
          </div>
        ) : (
          <a href="/login" className="text-sm text-brand-400 hover:text-brand-300 px-3 py-1.5 rounded-lg hover:bg-brand-500/10 transition-colors">
            {t('header.login')}
          </a>
        )}
      </div>
    </header>
  );
}
```

**Step 3: 创建 Sidebar 组件**

webui/src/components/layout/Sidebar.tsx:
```typescript
import { useState, useEffect } from 'react';
import { Folder, ChevronRight, ChevronDown, Search } from 'lucide-react';
import { createApiClient } from '../../api/client';
import type { TreeItem } from '../../types/api';
import { useI18n } from '../../hooks/useI18n';

function TreeNode({ item, depth, filter }: { item: TreeItem; depth: number; filter: string }) {
  const [expanded, setExpanded] = useState(depth < 1);
  if (item.type === 'file') return null;

  return (
    <div>
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-slate-300 hover:text-white hover:bg-slate-800/50 transition-colors rounded-md"
        style={{ paddingLeft: (12 + depth * 16) + 'px' }}>
        {item.children ? (expanded ? <ChevronDown size={12} className="shrink-0" /> : <ChevronRight size={12} className="shrink-0" />) : <span className="w-3" />}
        <Folder size={14} className="shrink-0 text-brand-400" />
        <span className="truncate">{item.name}</span>
      </button>
      {expanded && item.children && (
        <div>{item.children.map(child => <TreeNode key={child.path} item={child} depth={depth + 1} filter={filter} />)}</div>
      )}
    </div>
  );
}

export default function Sidebar() {
  const [tree, setTree] = useState<TreeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const { t } = useI18n();

  useEffect(() => {
    const api = createApiClient();
    api.get<TreeItem[]>('tree').then(setTree).catch(() => {}).finally(() => setLoading(false));
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-slate-700/50">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input type="text" value={filter} onChange={e => setFilter(e.target.value)}
            placeholder={t('sidebar.filterPlaceholder')}
            className="w-full h-8 pl-7 pr-2 rounded-md bg-slate-800/50 border border-slate-700/50 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-brand-500/50" />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        {loading ? (
          <div className="text-xs text-slate-500 text-center py-4">{t('sidebar.loadingTree')}</div>
        ) : tree.length === 0 ? (
          <div className="text-xs text-slate-500 text-center py-4">{t('sidebar.noTree')}</div>
        ) : (
          tree.map(item => <TreeNode key={item.path} item={item} depth={0} filter={filter} />)
        )}
      </div>
    </div>
  );
}
```

**Step 4: 创建 InfoPanel 组件**

webui/src/components/layout/InfoPanel.tsx:
```typescript
import { X } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';

interface InfoPanelProps {
  onClose: () => void;
}

export default function InfoPanel({ onClose }: InfoPanelProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
        <h3 className="text-sm font-medium text-slate-200">{t('info.panel')}</h3>
        <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={14} /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <p className="text-xs text-slate-500 text-center">{t('info.noSelection')}</p>
      </div>
    </div>
  );
}
```

**Step 5: 创建 ResizablePanel 组件**

webui/src/components/layout/ResizablePanel.tsx:
```typescript
import { useRef, useState, useCallback, type ReactNode } from 'react';

interface ResizablePanelProps {
  children: ReactNode;
  defaultWidth?: number;
  minWidth?: number;
  maxWidth?: number;
  side?: 'left' | 'right';
}

export default function ResizablePanel({
  children, defaultWidth = 240, minWidth = 180, maxWidth = 400, side = 'left',
}: ResizablePanelProps) {
  const [width, setWidth] = useState(defaultWidth);
  const dragging = useRef(false);

  const onMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      setWidth(w => Math.min(maxWidth, Math.max(minWidth, w + e.movementX * (side === 'left' ? 1 : -1))));
    };
    const onMouseUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [minWidth, maxWidth, side]);

  return (
    <div style={{ width }} className="relative shrink-0">
      {children}
      <div className="absolute top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand-500/30 transition-colors z-10"
        style={{ [side]: 0 }} onMouseDown={onMouseDown} />
    </div>
  );
}
```


---

## Task 9: 搜索功能

**Covers:** [S9]

**Files:**
- Create: `webui/src/hooks/useSearch.ts`
- Modify: `webui/src/components/layout/Header.tsx` (搜索栏)

**Step 1: 创建 useSearch hook**

webui/src/hooks/useSearch.ts:
```typescript
import { useState, useEffect, useRef, useCallback } from 'react';
import { createApiClient } from '../api/client';
import { createFilesApi } from '../api/files';
import type { SearchResult } from '../types/api';

export function useSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const api = createFilesApi(createApiClient());

  const search = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    setLoading(true);
    try {
      const res = await api.search(q);
      setResults(res.results);
      setOpen(true);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!query.trim()) { setResults([]); setOpen(false); return; }
    timer.current = setTimeout(() => search(query), 200);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [query, search]);

  const clear = useCallback(() => {
    setQuery('');
    setResults([]);
    setOpen(false);
  }, []);

  return { query, setQuery, results, loading, open, setOpen, clear };
}
```

**Step 2: 更新 Header 集成搜索**

webui/src/components/layout/Header.tsx (搜索部分替换为带下拉的搜索组件):

在 Header 组件中，将原有的搜索 input 替换为以下集成搜索的版本。使用 `useSearch` hook 管理搜索状态，在搜索框下方渲染搜索结果下拉面板。


---

## Task 8: 文件浏览 - BrowsePage + 项目视图

**Covers:** [S6, S9]

**Files:**
- Create: `webui/src/api/files.ts`
- Create: `webui/src/api/thumbnails.ts`
- Create: `webui/src/hooks/useProjects.ts`
- Create: `webui/src/hooks/useThumbnailCache.ts`
- Create: `webui/src/components/files/ProjectGrid.tsx`
- Create: `webui/src/components/files/ProjectList.tsx`
- Create: `webui/src/components/files/ProjectCard.tsx`
- Create: `webui/src/components/files/Breadcrumb.tsx`
- Create: `webui/src/components/files/FileToolbar.tsx`
- Modify: `webui/src/pages/BrowsePage.tsx`

**Step 1: 创建 files.ts API**

webui/src/api/files.ts:
```typescript
import type { ApiClient } from './client';
import type { FilesResponse, ProjectDetail, HomeData, SearchResponse, TreeItem, Metadata, OkResponse } from '../types/api';

export function createFilesApi(api: ApiClient) {
  return {
    list: (path: string = '', sort?: string, order?: string) =>
      api.get<FilesResponse>('projects', { path, sort, order }),
    detail: (fpath: string) =>
      api.get<ProjectDetail>('projects', { path: fpath }),
    home: () =>
      api.get<HomeData>('home'),
    tree: () =>
      api.get<TreeItem[]>('tree'),
    search: (q: string, category?: string) =>
      api.get<SearchResponse>('search', { q, category }),
    meta: (fpath: string) =>
      api.get<Metadata>('meta/' + encodeURIComponent(fpath)),
    saveMeta: (fpath: string, data: Partial<Metadata>) =>
      api.put<OkResponse>('meta/' + encodeURIComponent(fpath), data),
    download: (fpath: string) =>
      '/api/download/' + encodeURIComponent(fpath),
  };
}

export type FilesApi = ReturnType<typeof createFilesApi>;
```

**Step 2: 创建 thumbnails.ts API**

webui/src/api/thumbnails.ts:
```typescript
import type { ApiClient } from './client';
import type { ThumbnailBatchResponse } from '../types/api';

export function createThumbnailApi(api: ApiClient) {
  return {
    batch: (paths: string[], size: number = 200) =>
      api.post<ThumbnailBatchResponse>('thumbnails/batch', { paths, size }),
  };
}

export type ThumbnailApi = ReturnType<typeof createThumbnailApi>;
```

**Step 3: 创建 useProjects hook**

webui/src/hooks/useProjects.ts:
```typescript
import { useState, useEffect, useCallback } from 'react';
import { createApiClient } from '../api/client';
import { createFilesApi } from '../api/files';
import type { FilesResponse } from '../types/api';

export type SortField = 'name' | 'size' | 'modified' | 'type';
export type SortOrder = 'asc' | 'desc';
export type ViewMode = 'grid' | 'list';

export function useProjects(initialPath: string = '') {
  const [path, setPath] = useState(initialPath);
  const [data, setData] = useState<FilesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortOrder, setSortOrder] = useState<SortOrder>('asc');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const api = createFilesApi(createApiClient());

  const load = useCallback(async (p: string) => {
    setLoading(true);
    setError(null);
    setSelected(new Set());
    try {
      const res = await api.list(p, sortField, sortOrder);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [api, sortField, sortOrder]);

  useEffect(() => { load(path); }, [path, load]);

  const navigate = useCallback((newPath: string) => setPath(newPath), []);
  const toggleSelect = useCallback((itemPath: string) => {
    setSelected(prev => { const next = new Set(prev); if (next.has(itemPath)) next.delete(itemPath); else next.add(itemPath); return next; });
  }, []);
  const toggleSort = useCallback((field: SortField) => {
    setSortOrder(prev => sortField === field ? (prev === 'asc' ? 'desc' : 'asc') : 'asc');
    setSortField(field);
  }, [sortField]);

  return { path, data, loading, error, sortField, sortOrder, viewMode, selected,
    setViewMode, toggleSort, navigate, toggleSelect, setSelected, reload: () => load(path) };
}
```

**Step 4: 创建 useThumbnailCache hook**

webui/src/hooks/useThumbnailCache.ts:
```typescript
import { useState, useCallback } from 'react';
import { createApiClient } from '../api/client';
import { createThumbnailApi } from '../api/thumbnails';

const CACHE_KEY = 'am_thumb_cache';
const CACHE_SIZE = 200;

function getCache(): Record<string, string> {
  try { return JSON.parse(sessionStorage.getItem(CACHE_KEY) || '{}'); } catch { return {}; }
}

function setCache(cache: Record<string, string>) {
  const keys = Object.keys(cache);
  if (keys.length > CACHE_SIZE) {
    const trimmed: Record<string, string> = {};
    keys.slice(-CACHE_SIZE).forEach(k => { trimmed[k] = cache[k]!; });
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(trimmed));
  } else {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  }
}

export function useThumbnailCache() {
  const [cache, setCacheState] = useState<Record<string, string>>(getCache());
  const loadThumbnails = useCallback(async (paths: string[]) => {
    const uncached = paths.filter(p => !cache[p]);
    if (uncached.length === 0) return;
    try {
      const api = createThumbnailApi(createApiClient());
      const res = await api.batch(uncached);
      setCacheState(prev => { const updated = { ...prev, ...res.thumbnails }; setCache(updated); return updated; });
    } catch { /* ignore */ }
  }, [cache]);
  const getThumbnail = useCallback((path: string): string | undefined => cache[path], [cache]);
  return { getThumbnail, loadThumbnails };
}
```

**Step 5: 创建 ProjectCard 组件**

webui/src/components/files/ProjectCard.tsx:
```typescript
import { File, Folder, FileImage, FileVideo, FileAudio, FileArchive, FileCode } from 'lucide-react';
import type { ProjectItem } from '../../types/api';

const categoryIcons: Record<string, typeof File> = {
  image: FileImage, video: FileVideo, audio: FileAudio, archive: FileArchive, code: FileCode, document: File,
};

interface ProjectCardProps {
  item: ProjectItem;
  selected: boolean;
  onSelect: () => void;
  onClick: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  thumbnailUrl?: string;
}

export default function ProjectCard({ item, selected, onSelect, onClick, onContextMenu, thumbnailUrl }: ProjectCardProps) {
  const Icon = categoryIcons[item.category] ?? File;
  return (
    <div onContextMenu={onContextMenu} onClick={onClick}
      className={'group relative rounded-xl border overflow-hidden cursor-pointer transition-all duration-150 ' +
        (selected ? 'border-brand-500 bg-brand-500/10 ring-1 ring-brand-500/30' : 'border-slate-700/50 bg-slate-900 hover:border-slate-600/50 hover:bg-slate-800/50')}>
      {thumbnailUrl ? (
        <div className="aspect-video bg-slate-800 overflow-hidden">
          <img src={thumbnailUrl} alt={item.name} className="w-full h-full object-cover" loading="lazy" />
        </div>
      ) : (
        <div className="aspect-video flex items-center justify-center bg-slate-800/50">
          <Icon size={32} className={item.type === 'dir' ? 'text-brand-400' : 'text-slate-500'} />
        </div>
      )}
      <div className="absolute top-2 left-2" onClick={e => { e.stopPropagation(); onSelect(); }}>
        <div className={'w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ' +
          (selected ? 'bg-brand-500 border-brand-500' : 'border-slate-500/50 bg-slate-900/80 opacity-0 group-hover:opacity-100')}>
          {selected && <span className="text-white text-xs">&#x2713;</span>}
        </div>
      </div>
      <div className="p-3">
        <p className="text-sm text-slate-200 truncate font-medium">{item.name}</p>
        <p className="text-xs text-slate-500 mt-1">{item.size_fmt}</p>
      </div>
    </div>
  );
}
```

**Step 6: 创建 ProjectGrid 组件**

webui/src/components/files/ProjectGrid.tsx:
```typescript
import { useRef, useEffect } from 'react';
import ProjectCard from './ProjectCard';
import type { ProjectItem } from '../../types/api';

interface ProjectGridProps {
  items: ProjectItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onNavigate: (path: string) => void;
  onContextMenu?: (e: React.MouseEvent, item: ProjectItem) => void;
  thumbnailMap: Record<string, string>;
  loadThumbnails: (paths: string[]) => void;
}

export default function ProjectGrid({ items, selected, onSelect, onNavigate, onContextMenu, thumbnailMap, loadThumbnails }: ProjectGridProps) {
  const loaded = useRef(false);

  useEffect(() => {
    if (!loaded.current && items.length > 0) {
      loaded.current = true;
      const imageItems = items.filter(i => i.category === 'image' || i.thumbnail_url);
      if (imageItems.length > 0) loadThumbnails(imageItems.map(i => i.path));
    }
  }, [items, loadThumbnails]);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 p-4">
      {items.map(item => (
        <ProjectCard key={item.path} item={item}
          selected={selected.has(item.path)}
          onSelect={() => onSelect(item.path)}
          onClick={() => { if (item.type === 'dir') onNavigate(item.path); }}
          onContextMenu={onContextMenu ? (e) => onContextMenu(e, item) : undefined}
          thumbnailUrl={thumbnailMap[item.path] || item.thumbnail_url} />
      ))}
    </div>
  );
}
```

**Step 7: 创建 ProjectList 组件**

webui/src/components/files/ProjectList.tsx:
```typescript
import { File, Folder, ChevronRight } from 'lucide-react';
import type { ProjectItem } from '../../types/api';

interface ProjectListProps {
  items: ProjectItem[];
  selected: Set<string>;
  onSelect: (path: string) => void;
  onNavigate: (path: string) => void;
}

export default function ProjectList({ items, selected, onSelect, onNavigate }: ProjectListProps) {
  return (
    <div className="divide-y divide-slate-800/50">
      {items.map(item => (
        <div key={item.path}
          onClick={() => { if (item.type === 'dir') onNavigate(item.path); }}
          className={'flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors text-sm ' +
            (selected.has(item.path) ? 'bg-brand-500/10' : 'hover:bg-slate-800/50')}>
          <div onClick={e => { e.stopPropagation(); onSelect(item.path); }}
            className={'w-4 h-4 rounded border flex items-center justify-center shrink-0 ' +
              (selected.has(item.path) ? 'bg-brand-500 border-brand-500' : 'border-slate-600')}>
            {selected.has(item.path) && <span className="text-white text-[10px]">&#x2713;</span>}
          </div>
          {item.type === 'dir' ? <Folder size={16} className="text-brand-400 shrink-0" /> : <File size={16} className="text-slate-500 shrink-0" />}
          <span className="flex-1 truncate text-slate-200">{item.name}</span>
          <span className="text-xs text-slate-500 w-20 text-right">{item.size_fmt}</span>
          {item.type === 'dir' && <ChevronRight size={14} className="text-slate-600 shrink-0" />}
        </div>
      ))}
    </div>
  );
}
```

**Step 8: 创建 Breadcrumb 组件**

webui/src/components/files/Breadcrumb.tsx:
```typescript
import { ChevronRight, Home } from 'lucide-react';

interface BreadcrumbProps {
  path: string;
  onNavigate: (path: string) => void;
}

export default function Breadcrumb({ path, onNavigate }: BreadcrumbProps) {
  const parts = path ? path.split('/').filter(Boolean) : [];

  return (
    <nav className="flex items-center gap-1 text-sm px-4 py-2 border-b border-slate-700/50 overflow-x-auto">
      <button onClick={() => onNavigate('')} className="text-slate-400 hover:text-white transition-colors shrink-0">
        <Home size={14} />
      </button>
      {parts.length > 0 && <ChevronRight size={12} className="text-slate-600 shrink-0" />}
      {parts.map((part, i) => {
        const fullPath = parts.slice(0, i + 1).join('/');
        const isLast = i === parts.length - 1;
        return (
          <span key={i} className="flex items-center gap-1">
            {isLast ? (
              <span className="text-slate-200 font-medium truncate max-w-[200px]">{part}</span>
            ) : (
              <>
                <button onClick={() => onNavigate(fullPath)} className="text-slate-400 hover:text-white transition-colors truncate max-w-[150px]">{part}</button>
                <ChevronRight size={12} className="text-slate-600 shrink-0" />
              </>
            )}
          </span>
        );
      })}
    </nav>
  );
}
```

**Step 9: 创建 FileToolbar 组件**

webui/src/components/files/FileToolbar.tsx:
```typescript
import { Grid, List, ArrowUp, ArrowDown, RefreshCw, Upload } from 'lucide-react';
import { useI18n } from '../../hooks/useI18n';
import type { SortField, SortOrder, ViewMode } from '../../hooks/useProjects';

interface FileToolbarProps {
  sortField: SortField;
  sortOrder: SortOrder;
  viewMode: ViewMode;
  onToggleSort: (field: SortField) => void;
  onSetViewMode: (mode: ViewMode) => void;
  onRefresh: () => void;
  selectedCount: number;
  totalCount: number;
}

export default function FileToolbar({ sortField, sortOrder, viewMode, onToggleSort, onSetViewMode, onRefresh, selectedCount, totalCount }: FileToolbarProps) {
  const { t } = useI18n();

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-slate-700/50 bg-slate-900/30">
      <div className="flex items-center gap-1 text-xs text-slate-500">
        <span>{totalCount} items</span>
        {selectedCount > 0 && <span className="text-brand-400">({selectedCount} selected)</span>}
      </div>
      <div className="flex-1" />
      <button onClick={onRefresh} className="text-slate-400 hover:text-white p-1 rounded hover:bg-slate-800/50 transition-colors" title={t('action.refresh')}>
        <RefreshCw size={14} />
      </button>
      <div className="flex items-center gap-1 border-l border-slate-700/50 pl-2">
        <button onClick={() => onSetViewMode('grid')} className={'p-1 rounded transition-colors ' + (viewMode === 'grid' ? 'text-brand-400 bg-slate-800/50' : 'text-slate-400 hover:text-white')}>
          <Grid size={14} />
        </button>
        <button onClick={() => onSetViewMode('list')} className={'p-1 rounded transition-colors ' + (viewMode === 'list' ? 'text-brand-400 bg-slate-800/50' : 'text-slate-400 hover:text-white')}>
          <List size={14} />
        </button>
      </div>
      <div className="flex items-center gap-1 border-l border-slate-700/50 pl-2">
        {(['name', 'size', 'modified'] as SortField[]).map(field => (
          <button key={field} onClick={() => onToggleSort(field)}
            className={'flex items-center gap-1 px-2 py-1 rounded text-xs transition-colors ' +
              (sortField === field ? 'text-brand-400 bg-slate-800/50' : 'text-slate-400 hover:text-white')}>
            {t('sort.' + field)}
            {sortField === field && (sortOrder === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
          </button>
        ))}
      </div>
    </div>
  );
}
```

**Step 10: 更新 BrowsePage 集成所有组件**

webui/src/pages/BrowsePage.tsx:
```typescript
import { useCallback } from 'react';
import AppLayout from '../components/layout/AppLayout';
import Breadcrumb from '../components/files/Breadcrumb';
import FileToolbar from '../components/files/FileToolbar';
import ProjectGrid from '../components/files/ProjectGrid';
import ProjectList from '../components/files/ProjectList';
import { useProjects } from '../hooks/useProjects';
import { useThumbnailCache } from '../hooks/useThumbnailCache';
import { useI18n } from '../hooks/useI18n';

export default function BrowsePage() {
  const { path, data, loading, error, sortField, sortOrder, viewMode, selected, setViewMode, toggleSort, navigate, toggleSelect, reload } = useProjects('');
  const { getThumbnail, loadThumbnails } = useThumbnailCache();
  const { t } = useI18n();

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
  }, []);

  return (
    <AppLayout>
      <div className="flex flex-col h-full" onContextMenu={handleContextMenu}>
        <Breadcrumb path={path} onNavigate={navigate} />
        <FileToolbar
          sortField={sortField} sortOrder={sortOrder} viewMode={viewMode}
          onToggleSort={toggleSort} onSetViewMode={setViewMode}
          onRefresh={reload} selectedCount={selected.size} totalCount={data?.items.length ?? 0} />
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <p className="text-slate-500 text-sm">{t('browse.loading')}</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center h-64 gap-2">
              <p className="text-red-400 text-sm">{error}</p>
              <button onClick={reload} className="text-xs text-brand-400 hover:text-brand-300">{t('app.retry')}</button>
            </div>
          ) : data && data.items.length === 0 ? (
            <div className="flex items-center justify-center h-64">
              <p className="text-slate-500 text-sm">{t('browse.empty')}</p>
            </div>
          ) : viewMode === 'grid' ? (
            <ProjectGrid items={data?.items ?? []} selected={selected}
              onSelect={toggleSelect} onNavigate={navigate} loadThumbnails={loadThumbnails}
              thumbnailMap={{}} />
          ) : (
            <ProjectList items={data?.items ?? []} selected={selected}
              onSelect={toggleSelect} onNavigate={navigate} />
          )}
        </div>
      </div>
    </AppLayout>
  );
}
```
---

## Task 10: 标签系统

**Covers:** [S9]

**Files:**
- Create: `webui/src/api/tags.ts`
- Create: `webui/src/components/tags/TagChip.tsx`
- Modify: `webui/src/components/layout/InfoPanel.tsx` (标签区域)

**Step 1: 创建 src/api/tags.ts**

```typescript
import type { ApiClient } from "./client";
import type { TagsResponse, OkResponse } from "../types/api";

export function createTagsApi(api: ApiClient) {
  return {
    list: () => api.get<TagsResponse>("tags"),
    add: (tag: string, filePath: string) =>
      api.post<OkResponse>("tags", { tag, file_path: filePath }),
    rename: (oldName: string, newName: string) =>
      api.put<OkResponse>(`tags/${encodeURIComponent(oldName)}`, { new_name: newName }),
    delete: (name: string) =>
      api.delete<OkResponse>(`tags/${encodeURIComponent(name)}`),
  };
}

export type TagsApi = ReturnType<typeof createTagsApi>;
```

**Step 2: 创建 TagChip.tsx**

```typescript
import { X } from "lucide-react";

interface TagChipProps {
  name: string;
  count?: number;
  onRemove?: () => void;
  onClick?: () => void;
}

export function TagChip({ name, count, onRemove, onClick }: TagChipProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium
        bg-brand-500/10 text-brand-300 border border-brand-500/20
        ${onClick ? "cursor-pointer hover:bg-brand-500/20" : ""}`}
      onClick={onClick}
    >
      {name}
      {count != null && <span className="text-brand-400">({count})</span>}
      {onRemove && (
        <button onClick={(e) => { e.stopPropagation(); onRemove(); }} className="ml-0.5 hover:text-white">
          <X size={12} />
        </button>
      )}
    </span>
  );
}
```

---

## Task 11: 项目详情页

**Covers:** [S9]

**Files:**
- Create: `webui/src/api/metadata.ts`
- Modify: `webui/src/pages/DetailPage.tsx`

**Step 1: 创建 src/api/metadata.ts**

```typescript
import type { ApiClient } from "./client";
import type { ProjectDetail, Metadata, SearchResponse } from "../types/api";

export function createMetadataApi(api: ApiClient) {
  return {
    getProjectDetail: (path: string) =>
      api.get<ProjectDetail>(`projects/${encodeURIComponent(path)}`),
    getMeta: (path: string) =>
      api.get<Metadata>(`meta/${encodeURIComponent(path)}`),
    search: (q: string, tags?: string, category?: string) =>
      api.get<SearchResponse>("search", { q, tags, category }),
    getTree: () => api.get<ProjectDetail>("tree"),
    getHome: () => api.get<ProjectDetail>("home"),
  };
}

export type MetadataApi = ReturnType<typeof createMetadataApi>;
```

**Step 2: 实现 DetailPage**

DetailPage 包含 Hero 区、文件列表、图片画廊。从 URL `?path=` 读取路径。

```typescript
import { useState, useEffect } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useAuth } from "../hooks/useAuth";
import { createMetadataApi } from "../api/metadata";
import type { ProjectDetail } from "../types/api";
import { ImageViewer } from "../components/viewer/ImageViewer";
import { Skeleton } from "../components/ui/Skeleton";

export default function DetailPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const path = searchParams.get("path") || "";
  const { api } = useAuth();
  const metaApi = createMetadataApi(api);

  const [data, setData] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!path) { setLoading(false); return; }
    setLoading(true);
    metaApi.getProjectDetail(path)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [path]);

  return (
    <div className="min-h-screen bg-slate-950 p-6">
      <button onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-slate-400 hover:text-white mb-6 transition-colors">
        <ArrowLeft size={20} /> Back
      </button>

      {loading ? (
        <div className="space-y-4">
          <Skeleton className="h-48 w-full rounded-xl" />
          <Skeleton className="h-6 w-1/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ) : data ? (
        <>
          <div className="relative rounded-xl overflow-hidden bg-slate-900 border border-slate-700/50 mb-8">
            {data.images?.[0] && (
              <img src={data.images[0]} alt="" className="w-full h-48 object-cover opacity-60" />
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-slate-900 via-slate-900/60 to-transparent" />
            <div className="relative p-6">
              <h1 className="text-2xl font-bold text-white">{data.name}</h1>
              <p className="text-slate-400 mt-1">{data.size_fmt}</p>
            </div>
          </div>

          {data.images && data.images.length > 0 && (
            <div className="mb-8">
              <h2 className="text-lg font-semibold text-white mb-4">Images</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                {data.images.map((img, i) => (
                  <button key={i} onClick={() => setViewerIndex(i)}
                    className="aspect-square rounded-lg overflow-hidden border border-slate-700/50 hover:border-brand-500/50 transition-colors">
                    <img src={img} alt="" className="w-full h-full object-cover" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {data.items && data.items.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold text-white mb-4">Files</h2>
              <div className="space-y-1">
                {data.items.map(item => (
                  <div key={item.path}
                    className="flex items-center gap-3 px-4 py-2 rounded-lg hover:bg-slate-800/50 transition-colors">
                    <span className="text-slate-400 text-sm flex-1">{item.name}</span>
                    <span className="text-slate-500 text-xs">{item.size_fmt}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <p className="text-slate-500 text-center mt-20">Project not found</p>
      )}

      {viewerIndex !== null && data?.images && (
        <ImageViewer images={data.images} currentIndex={viewerIndex}
          onClose={() => setViewerIndex(null)} onIndexChange={setViewerIndex} />
      )}
    </div>
  );
}
```

---

## Task 12: 分享系统

**Covers:** [S9]

**Files:**
- Create: `webui/src/api/shares.ts`
- Create: `webui/src/components/shares/ShareDialog.tsx`
- Create: `webui/src/components/shares/SharePage.tsx`
- Modify: `webui/src/pages/ShareReceivePage.tsx`

**Step 1: 创建 src/api/shares.ts**

```typescript
import type { ApiClient } from "./client";
import type { ShareLink, ShareCreateRequest, ShareVerifyResponse, ShareInfoResponse, OkResponse } from "../types/api";

export function createSharesApi(api: ApiClient) {
  return {
    create: (data: ShareCreateRequest) =>
      api.post<ShareLink>("shares", data),
    list: () => api.get<{ shares: ShareLink[] }>("shares"),
    delete: (id: string) => api.delete<OkResponse>(`shares/${id}`),
    getInfo: (id: string) => api.get<ShareInfoResponse>(`shares/${id}/info`),
    verifyPassword: (id: string, password: string) =>
      api.post<ShareVerifyResponse>(`shares/${id}/verify`, { password }),
    getDownloadUrl: (id: string, path: string) => `/api/shares/${id}/download/${path}`,
    getPreviewUrl: (id: string, path: string) => `/api/shares/${id}/preview/${path}`,
  };
}

export type SharesApi = ReturnType<typeof createSharesApi>;
```

**Step 2: ShareDialog.tsx** - Modal 弹窗，包含表单：密码、有效期、最大下载次数、允许预览。从文件右键菜单触发。

**Step 3: SharePage.tsx** - 分享文件展示组件，显示文件列表网格，支持下载。

**Step 4: 实现 ShareReceivePage** - 从 URL 获取 shareId，检查是否需要密码，验证后显示分享内容。

---

## Task 13: 图片查看器

**Covers:** [S9]

**Files:**
- Create: `webui/src/components/viewer/ImageViewer.tsx`

全屏 Overlay 图片查看器，支持缩放(滚轮)、平移(拖拽)、方向键导航、ESC 关闭。

```typescript
import { useState, useEffect, useCallback, useRef } from "react";
import { X, ZoomIn, ZoomOut, RotateCcw, ChevronLeft, ChevronRight } from "lucide-react";

interface ImageViewerProps {
  images: string[];
  currentIndex: number;
  onClose: () => void;
  onIndexChange?: (index: number) => void;
}

export function ImageViewer({ images, currentIndex, onClose, onIndexChange }: ImageViewerProps) {
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [index, setIndex] = useState(currentIndex);
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef({ startX: 0, startY: 0, startPosX: 0, startPosY: 0 });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft") prev();
      if (e.key === "ArrowRight") next();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [index]);

  const prev = () => {
    const i = index > 0 ? index - 1 : images.length - 1;
    setIndex(i); setScale(1); setPosition({ x: 0, y: 0 });
    onIndexChange?.(i);
  };

  const next = () => {
    const i = index < images.length - 1 ? index + 1 : 0;
    setIndex(i); setScale(1); setPosition({ x: 0, y: 0 });
    onIndexChange?.(i);
  };

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setScale(s => Math.max(0.5, Math.min(5, s - e.deltaY * 0.01)));
  }, []);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (scale <= 1) return;
    setIsDragging(true);
    dragRef.current = { startX: e.clientX, startY: e.clientY, startPosX: position.x, startPosY: position.y };
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPosition({
      x: dragRef.current.startPosX + (e.clientX - dragRef.current.startX),
      y: dragRef.current.startPosY + (e.clientY - dragRef.current.startY),
    });
  };

  const handleMouseUp = () => setIsDragging(false);

  return (
    <div className="fixed inset-0 z-50 bg-black/95 flex flex-col"
      onWheel={handleWheel} onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove} onMouseUp={handleMouseUp}>
      <div className="flex items-center justify-between px-4 py-3 bg-black/50">
        <span className="text-sm text-slate-400">{index + 1} / {images.length}</span>
        <div className="flex items-center gap-3">
          <button onClick={() => setScale(s => Math.min(5, s + 0.5))} className="text-white/70 hover:text-white"><ZoomIn size={20} /></button>
          <button onClick={() => setScale(s => Math.max(0.5, s - 0.5))} className="text-white/70 hover:text-white"><ZoomOut size={20} /></button>
          <button onClick={() => { setScale(1); setPosition({ x: 0, y: 0 }); }} className="text-white/70 hover:text-white"><RotateCcw size={20} /></button>
          <button onClick={onClose} className="text-white/70 hover:text-white"><X size={24} /></button>
        </div>
      </div>
      <div className="flex-1 flex items-center justify-center relative overflow-hidden">
        {images.length > 1 && (
          <button onClick={prev} className="absolute left-4 z-10 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white">
            <ChevronLeft size={28} />
          </button>
        )}
        <img src={images[index]} alt={`Image ${index + 1}`}
          className="max-w-full max-h-full transition-transform duration-100 select-none"
          style={{
            transform: `scale(${scale}) translate(${position.x / scale}px, ${position.y / scale}px)`,
            cursor: scale > 1 ? "grab" : "default",
          }}
          draggable={false} />
        {images.length > 1 && (
          <button onClick={next} className="absolute right-4 z-10 p-2 rounded-full bg-black/50 hover:bg-black/70 text-white">
            <ChevronRight size={28} />
          </button>
        )}
      </div>
    </div>
  );
}
```

---

## Task 14: 管理功能

**Covers:** [S9, S10]

**Files:**
- Create: `webui/src/api/users.ts`
- Create: `webui/src/components/admin/UserManagement.tsx`
- Create: `webui/src/components/admin/InviteManagement.tsx`
- Create: `webui/src/components/admin/ShareManagement.tsx`
- Create: `webui/src/components/admin/ActivityLog.tsx`
- Create: `webui/src/components/admin/OnlineUsers.tsx`

**Step 1: 创建 src/api/users.ts**

```typescript
import type { ApiClient } from "./client";
import type { UsersResponse, InvitesResponse, ActivityResponse, OnlineUsersResponse, OkResponse } from "../types/api";

export function createUsersApi(api: ApiClient) {
  return {
    list: () => api.get<UsersResponse>("users"),
    toggleUser: (id: number, active: boolean) =>
      api.post<OkResponse>(`users/${id}/toggle`, { active }),
    listInvites: () => api.get<InvitesResponse>("invites"),
    createInvite: () => api.post<{ code: string }>("invites", {}),
    revokeInvite: (code: string) =>
      api.post<OkResponse>(`invites/${encodeURIComponent(code)}/revoke`, {}),
    getActivity: () => api.get<ActivityResponse>("activity"),
    getOnlineUsers: () => api.get<OnlineUsersResponse>("online-users"),
  };
}

export type UsersApi = ReturnType<typeof createUsersApi>;
```

**Step 2-6: 管理组件** - 每个组件是独立面板，在管理页面中以 Tab 形式组织。仅管理员可见。

---

## Task 15: 响应式适配

**Covers:** [S5, S9]

**Files:**
- Create: `webui/src/hooks/useMediaQuery.ts`
- Modify: 各布局组件

**Step 1: useMediaQuery hook**

```typescript
import { useState, useEffect } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);
  return matches;
}
```

AppLayout 断点: >=1024px 三栏, 768-1023px 两栏(Sidebar overlay), <768px 单栏(底部操作栏)。

---

## Task 16: 深色/浅色主题切换

**Covers:** [S10]

**Files:**
- Create: `webui/src/hooks/useTheme.ts`
- Modify: `webui/src/components/layout/Header.tsx`

```typescript
import { useState, useEffect, useCallback } from "react";

type Theme = "dark" | "light";

function getStoredTheme(): Theme {
  return (localStorage.getItem("am_theme") as Theme) || "dark";
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme === "light");
    localStorage.setItem("am_theme", theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setThemeState(t => t === "dark" ? "light" : "dark");
  }, []);

  return { theme, toggleTheme };
}
```

---

## Task 17: WebSocket 实时更新

**Covers:** [S7, S9]

**Files:**
- Create: `webui/src/hooks/useWebSocket.ts`

```typescript
import { useEffect, useRef, useCallback, useState } from "react";

type WebSocketStatus = "connecting" | "connected" | "disconnected";

interface UseWebSocketOptions {
  getToken: () => string | null;
  onEvent?: (type: string, data: any) => void;
  enabled?: boolean;
}

export function useWebSocket({ getToken, onEvent, enabled = true }: UseWebSocketOptions) {
  const [status, setStatus] = useState<WebSocketStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (!enabled) return;
    const token = getToken();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws${token ? `?token=${token}` : ""}`;

    setStatus("connecting");
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => { setStatus("connected"); retryRef.current = 0; };
    ws.onmessage = (event) => {
      try { const data = JSON.parse(event.data); onEvent?.(data.type, data); } catch {}
    };
    ws.onclose = () => {
      setStatus("disconnected");
      wsRef.current = null;
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000);
      retryRef.current++;
      timerRef.current = setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
  }, [getToken, onEvent, enabled]);

  useEffect(() => {
    connect();
    return () => { clearTimeout(timerRef.current); wsRef.current?.close(); };
  }, [connect]);

  return { status };
}
```

---

## Task 18: 后端集成 + 最终验证

**Covers:** [S11]

**Files:**
- Modify: `AssetsManager/lan/api.py`

**Step 1: 生产构建**

```bash
cd webui
npm run build
```

**Step 2: 更新后端路由**

修改 `AssetsManager/lan/api.py` 中的 `setup_routes()`，添加新前端路由：

```python
def setup_routes(app: web.Application, static_dir: Path):
    # ... existing routes ...

    # New WebUI SPA
    webui_dist = static_dir.parent.parent.parent / "webui" / "dist"
    if webui_dist.exists():
        assets_dir = webui_dist / "assets"
        if assets_dir.exists():
            app.router.add_static("/assets", str(assets_dir), name="webui_assets")
        app.router.add_get("/", lambda r: web.FileResponse(str(webui_dist / "index.html")))
```

**Step 3: 端到端验证清单**

- [ ] Landing 页显示服务器信息
- [ ] 登录/注册/密钥验证
- [ ] 目录树展开/导航
- [ ] 文件网格/列表视图 + 排序
- [ ] 搜索（文件名 + 标签）
- [ ] 文件下载（单文件 + 批量ZIP）
- [ ] 创建分享链接（密码/有效期/限次）
- [ ] 分享接收页（密码验证）
- [ ] 图片查看器（缩放/平移/导航）
- [ ] 管理面板（用户/邀请码/分享管理/活动日志/在线用户）
- [ ] 中/英/日语言切换
- [ ] 深色/浅色主题切换
- [ ] 移动端响应式布局
- [ ] WebSocket 实时更新