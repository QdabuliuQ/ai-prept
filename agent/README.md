# WebPPT Agent（PPT Master）

Python CLI：**PPT Master** 线路 — 规范 SVG → 原生 PPTX → 转 **html-slide** 模板包（需仓库根 `ppt-master/`）。

```text
agent-output/<template-id>/
├── template.json          # format: ppt-master；可含 visual_spec_outline
├── theme.css
├── images/
└── slides/*.html
# visual-spec.md 生成期不写，上传时再补
```

## 安装

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e .
```

## 用法

前置：仓库根已有 `ppt-master/`（ZIP）且 `ppt-master/.venv` 已装依赖。

```bash
cd agent && source .venv/bin/activate

# Mock（不调 LLM，验证管线）
webppt-agent ppt-master --mock --pages 3 -- "冒烟测试"

# 真实 LLM + 文生图（默认；需 IMAGE_*；也可用 --with-images 强制开）
webppt-agent ppt-master --pages 7 --style photo-editorial --with-images -- \
  "AI 产品发布会，冲击力封面，禁止说明书式三栏白卡"

# 跳过生图（纯几何 SVG）
webppt-agent ppt-master --pages 7 --style dark-tech --skip-image -- \
  "AI 产品发布会，冲击力封面"

# Plan 后色板对比度精修（默认关；也可用 AGENT_PALETTE_REFINE=1）
webppt-agent ppt-master --palette-refine --pages 7 --style dark-tech --skip-image -- \
  "AI 产品发布会"

# 为已有模板包补写 visual-spec.md
webppt-agent visual-spec ../agent-output/my-deck --mock

# Admin：/admin → 生成模板（仅 SVG 线路）
```

视觉风格：磁盘权威在 `ppt-master/.../visual-styles/`；重建机读目录：

```bash
cd agent && source .venv/bin/activate
webppt-agent styles-catalog --list
# 或 python scripts/build-visual-style-catalog.py
```

Admin 下拉读 `_catalog.json`（`GET /api/admin/styles`）。变体卡放 `visual-styles/variants/`。

该线路默认执行 `svg_quality_checker --quick-generate --stage final` 门禁；失败后默认
`--svg-repair` 做 bounds/LLM 修复，两轮仍失败会 soft-pass 继续导出。
关修复：`--no-svg-repair`（只检不修）。开发冒烟可加 `--fast-preview` 整段跳过门禁
（`quality_gate=skipped-fast-preview`），不应作为生产交付路径。

配图：Plan 标 `need_image` + `image_role`（background|hero|panel|illustration）+ `image_aspect` →
`materialize_images` 按比例写入 `images/` → SVG 嵌 `<image>`；**生图=主视觉/插图，SVG=局部装饰**。
生成后做融合校验（缺图/无字/海量 circle/满版遮罩）并最多重试 1 次。

## 环境变量

已对接仓库根 `.env.local` 的 LLM（DeepSeek）。启动时还会读 `agent/.env`（可覆盖）。

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` / `LLM_API_KEYS` | **主力**：Plan / Slide HTML（默认 DeepSeek） |
| `LLM_BASE_URL` | 如 `https://api.deepseek.com` |
| `LLM_MODEL` | 如 `deepseek-v4-flash` |
| `LLM_LIGHT_*` / `SILICONFLOW_*` | **轻量**：Plan JSON 等短任务；有硅基 Key 时默认 `Qwen/Qwen3-8B` |
| `SILICONFLOW_API_KEY` / `SILICONFLOW_API_KEYS` | 硅基流动多 key 轮询 |
| `IMAGE_API_KEY` / `IMAGE_API_BASE_URL` / `IMAGE_MODEL` | ppt-master 文生图：`../images/*.png` |
| `IMAGE_ASPECT_RATIO` / `IMAGE_SIZE` | 缺省比例（`auto`→`16:9`）；单页仍以 plan `image_aspect` 为准 |
| `AGENT_SKIP_IMAGE=1` | 跳过生图，改纯色占位 |
| `AGENT_PALETTE_REFINE=1` | Plan 后 WCAG 色板精修（默认关；Admin「色板精修」开关） |
| `AGENT_SLIDE_CONCURRENCY` | 单包内页并行数，默认 4 |
| `AGENT_IMAGE_CONCURRENCY` | 单包配图并行数，默认 4 |

检查连通性：

```bash
webppt-agent doctor
```
