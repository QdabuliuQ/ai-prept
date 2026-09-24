# WebPPT

| 目录 | 职责 |
|------|------|
| `frontend/` | Vite + React SPA（模板墙 / 编辑器 / Admin） |
| `backend/` | Python FastAPI（gallery、admin、上传、生成） |
| `packages/` | 共享库（如 html-to-pptx） |
| `agent-output/` | 本地模板产物（运行时） |

## 开发

```bash
# 终端 1：后端 API :8787
cd backend && source .venv/bin/activate
pip install -e '.[api]'
webppt-backend serve

# 终端 2：前端 :5174
npm install
npm run dev
```

打开 [http://127.0.0.1:5174](http://127.0.0.1:5174)。

路由：`/` 模板墙 · `/editor` 编辑器 · `/admin` 后台 · `/templates` 本地模板库。  
`/api/*`、`/embed/*` 由 Vite 代理到 `GALLERY_API_URL`（默认 `http://127.0.0.1:8787`）。

## 构建

```bash
npm run build      # → frontend/dist
npm run preview
```

## 脚本

| 命令 | 说明 |
|------|------|
| `npm run dev` | 前端开发服务器 |
| `npm run dev:api` | 后端 API |
| `npm run build` | 前端生产构建 |
| `npm run preview` | 预览生产构建 |

## 技术栈

- 前端：Vite 6 · React 19 · React Router · Zustand · Ant Design · Tailwind
- 后端：FastAPI · PostgreSQL（模板墙）· 七牛上传 · PPT Master 管线
