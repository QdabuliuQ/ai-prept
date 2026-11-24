# AI Prept Backend

Python FastAPI：模板墙、Admin、prepare/上传、生成任务。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e '.[api]'
# 可选：启用 Playwright 虚拟浏览器检查
pip install -e '.[api,browser]'
python -m playwright install chromium

ai-prept-backend gallery-sync
ai-prept-backend serve   # http://127.0.0.1:8790
```

环境变量见仓库根 `.env.local` / `.env.example`（也会读 `backend/.env`）。

数据：
- 模板包：`../agent-output/<id>/`
- 模板墙目录：PostgreSQL（`DATABASE_URL`）

### 模板容量契约

模板使用前会编译 `capacity.json`，把复合文本拆成叶子槽，并记录：

- 页面、行列分组、槽位和字段顺序
- 每个字段的安全字数、真实文本框尺寸和是否禁止换行
- 结构指纹；版式或主题变化后契约自动标记为过期

```bash
ai-prept-backend capacity ../agent-output/<id>
ai-prept-backend capacity ../agent-output/<id> --render-baseline
ai-prept-backend render-check ../agent-output/<id>
# 强制使用 Playwright（未安装时会自动回退到本机 Chrome）
ai-prept-backend render-check ../agent-output/<id> --engine playwright --json /tmp/render-report.json
```

`render-check` 会在真实浏览器中检查文字裁切/越界、独立文本槽位重叠、文字与背景同色，以及低对比度。报告中的 `summary.status` 为 `passed`、`warning`、`failed` 或 `unavailable`。

Remix 只接受 `status=ready` 的契约。生成完成后，服务会用真实 Chrome 对比源模板与成品；新增溢出会自动重写一次，仍失败则恢复对应源文案，并将模板保留为待复核状态。编辑器 Agent 默认执行同一视觉检查，也可以通过 `--no-render-check` 跳过。
