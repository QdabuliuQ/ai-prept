# AI Prept Backend

Python FastAPI：模板墙、Admin、prepare/上传、生成任务。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e '.[api]'

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
```

Remix 只接受 `status=ready` 的契约。生成完成后，服务会用真实 Chrome 对比源模板与成品；新增溢出会自动重写一次，仍失败则恢复对应源文案，并将模板保留为待复核状态。
