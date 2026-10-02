<div align="center">

<img src="frontend/public/brand/ai-prept-logo.png" alt="Ai Prept" width="96" />

# WebPPT / Ai Prept

基于 HTML 幻灯片的模板墙、可视化编辑器与生成管线

[快速开始](#快速开始) · [功能](#功能) · [技术栈](#技术栈) · [目录结构](#目录结构) · [CLI](#后端-cli)

[![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=white)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-6-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)

</div>

---

<!-- TODO: 添加项目截图（首页 / 编辑器 / Admin） -->

> 选模板、填要求，即可套用生成 HTML 幻灯片；在浏览器里编辑文本与版式，并导出 PDF / 图片 / PPTX。

---

## 功能

| 功能 | 说明 |
|------|------|
| 模板墙 | `/` 浏览公开模板，填写要求后启动 remix 生成 |
| 可视化编辑器 | `/edit` 编辑 HTML 幻灯片：选中文本、改字号/样式、缩放平移画布 |
| 模板文件树 | 侧栏查看包内 `slides/`、`images/` 等资源，并预览图片 |
| Admin | `/admin` 管理模板、任务、生成与上传（需 `ADMIN_TOKEN`） |
| 本地模板库 | `/templates` 打开 `agent-output` 中的本地包 |
| 导出 | 编辑器导出 PDF、整页图片或 HTML→PPTX |
| PPT Master 管线 | 后端 CLI / Admin 驱动风格卡、remix、页面改写等 |

---

## 快速开始

### 1. 数据库

```bash
# 需要本机 Docker Desktop
docker compose up -d
```

Postgres 映射到 `127.0.0.1:5433`（用户 / 密码 / 库均为 `webppt`）。

### 2. 环境变量

```bash
cp .env.example .env.local
# 按需填写 LLM / 图片 API Key，并确认：
# DATABASE_URL=postgresql://webppt:webppt@127.0.0.1:5433/webppt
# ADMIN_TOKEN=...
```

也会读取 `backend/.env`（会覆盖同名变量）。

### 3. 后端 API（`:8787`）

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip setuptools wheel
pip install -e '.[api]'

webppt-backend gallery-sync
webppt-backend serve
```

或在仓库根目录（需已建好 `backend/.venv`）：

```bash
npm run dev:api
```

### 4. 前端（`:5174`）

```bash
npm install
npm run dev
```

打开 [http://127.0.0.1:5174](http://127.0.0.1:5174)。

| 路径 | 页面 |
|------|------|
| `/` | 模板墙 |
| `/edit` | 编辑器 |
| `/admin` | 管理后台 |
| `/templates` | 本地模板库 |

Vite 将 `/api/*`、`/embed/*` 代理到 `GALLERY_API_URL`（默认 `http://127.0.0.1:8787`）。

<details>
<summary>环境变量说明（节选）</summary>

| 变量 | 用途 |
|------|------|
| `DATABASE_URL` | 模板墙 / Admin 目录（PostgreSQL） |
| `ADMIN_TOKEN` | Admin API 鉴权 |
| `LLM_*` / 各厂商 Key | 文案生成、remix、灵感等 |
| `GALLERY_API_URL` | 前端开发代理目标（可选） |

完整列表见 [`.env.example`](.env.example)。

</details>

---

## 构建

```bash
npm run build      # 构建 slide-editor runtime + 前端 → frontend/dist
npm run preview    # 预览生产构建（同端口策略见 vite 配置）
```

---

## npm 脚本

| 命令 | 说明 |
|------|------|
| `npm run dev` | 前端开发服务器 |
| `npm run dev:api` | 启动后端 `webppt-backend serve` |
| `npm run build` | 生产构建 |
| `npm run preview` / `start` | 预览生产构建 |
| `npm run lint` | ESLint |
| `npm run format` | Prettier 格式化 |

---

## 目录结构

| 路径 | 职责 |
|------|------|
| `frontend/` | Vite + React SPA |
| `backend/` | FastAPI、Gallery、Admin、PPT Master、remix |
| `packages/html-to-pptx/` | HTML 幻灯片导出为 PPTX |
| `agent-output/` | 本地模板包产物（运行时，按模板 id 分目录） |
| `docker-compose.yml` | 本地 PostgreSQL 16 |
| `scripts/` | slide-editor / slide-vendor 构建脚本 |

---

## 后端 CLI

在 `backend/` 激活 venv 后：

```bash
webppt-backend doctor              # 检查 LLM 配置
webppt-backend gallery-sync        # 从磁盘同步模板到 Postgres
webppt-backend serve               # API :8787（同 gallery-serve）
webppt-backend remix-template ...  # 基于源模板套用内容
webppt-backend ppt-master ...      # PPT Master 生成管线
webppt-backend styles-catalog      # 风格卡目录
webppt-backend visual-spec ...     # 设计规范
webppt-backend rewrite-page ...    # 单页改写
```

更多参数见 `webppt-backend <command> -h` 与 [`backend/README.md`](backend/README.md)。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 19 · Vite 6 · TypeScript · React Router · Zustand · Tailwind · Radix UI · Less |
| 幻灯片 | HTML embed（`/embed/slide`）· iframe 内编辑 runtime · html-to-pptx / pptxgenjs · jsPDF |
| 后端 | Python 3.9+ · FastAPI · Uvicorn · psycopg |
| 数据 | PostgreSQL（目录）· `agent-output/`（模板包文件） |
| 可选 | 七牛上传 · 多厂商 LLM / 图片 API |

---

## 贡献

1. Fork 本仓库并创建分支  
2. `npm install`，按「快速开始」拉起 DB / API / 前端  
3. 提交前可运行 `npm run lint`  
4. 发起 Pull Request  

远程仓库：[QdabuliuQ/Web-PPT-React](https://github.com/QdabuliuQ/Web-PPT-React)

---

## Star History

<a href="https://star-history.com/#QdabuliuQ/Web-PPT-React&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=QdabuliuQ/Web-PPT-React&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=QdabuliuQ/Web-PPT-React&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=QdabuliuQ/Web-PPT-React&type=Date" />
  </picture>
</a>
