# WebPPT Backend

Python FastAPI：模板墙、Admin、prepare/上传、生成任务。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e '.[api]'

webppt-backend gallery-sync
webppt-backend serve   # http://127.0.0.1:8787
```

环境变量见仓库根 `.env.local` / `.env.example`（也会读 `backend/.env`）。

数据：
- 模板包：`../agent-output/<id>/`
- 模板墙目录：PostgreSQL（`DATABASE_URL`）
