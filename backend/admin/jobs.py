"""Admin generate / remix job runner — subprocess webppt-backend CLI."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from admin.fsutil import (
    cleanup_expired_sessions,
    jobs_dir,
    repo_root,
    templates_root,
    workspace_root,
)
from admin.providers import (
    image_env_for_selection,
    llm_env_for_dual,
    resolve_image_selection,
    resolve_llm_selection,
)

_jobs: dict[str, dict[str, Any]] = {}
_children: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_FAIL_LINE_RE = re.compile(
    r"(?:\[(?:remix|rewrite-page|generate-page|delete-page|editor-assist|style|pack)[^\]]*\]\s+)?FAIL\s*[—\-]\s*(.+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_MSG_IN_QUOTES_RE = re.compile(
    r"""['"]message['"]\s*:\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def _error_from_log(log: str | None, fallback: str) -> str:
    """Prefer the last FAIL line / API message over a bare exit code."""
    text = str(log or "")
    if not text.strip():
        return fallback
    matches = list(_FAIL_LINE_RE.finditer(text))
    raw = matches[-1].group(1).strip() if matches else ""
    if not raw:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            if "Error code:" in line or "UNAVAILABLE" in line or "high demand" in line.lower():
                raw = line
                break
    if not raw:
        return fallback
    quoted = _MSG_IN_QUOTES_RE.search(raw)
    if quoted:
        raw = quoted.group(1).strip()
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) > 400:
        raw = raw[:397] + "…"
    return raw or fallback


def _job_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def _persist(job: dict[str, Any]) -> None:
    path = _job_path(job["id"])
    # drop non-serializable
    data = {k: v for k, v in job.items() if not k.startswith("_")}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _initial_progress(total: int) -> dict[str, Any]:
    return {"total": total, "done": 0, "ok": 0, "fail": 0, "skip": 0, "percent": 0}


def _backend_bin() -> Path:
    backend = repo_root() / "backend"
    return backend / ".venv" / "bin" / "webppt-backend"


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
    if job:
        return dict(job)
    path = _job_path(job_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and data.get("id"):
        with _lock:
            _jobs[job_id] = data
        return dict(data)
    return None


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    load_recent_from_disk()
    with _lock:
        items = list(_jobs.values())
    items.sort(key=lambda j: j.get("createdAt") or "", reverse=True)
    return [dict(j) for j in items[:limit]]


def load_recent_from_disk() -> None:
    root = jobs_dir()
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    with _lock:
        for path in files[:80]:
            if path.name.endswith("-report.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("id"):
                existing = _jobs.get(data["id"])
                if existing and existing.get("status") == "running" and data.get("status") != "running":
                    _jobs[data["id"]] = data
                elif data["id"] not in _jobs:
                    _jobs[data["id"]] = data


def refresh_job_from_disk(job_id: str) -> dict[str, Any] | None:
    path = _job_path(job_id)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                with _lock:
                    mem = _jobs.get(job_id)
                    if mem and mem.get("status") == "running" and data.get("status") == "running":
                        # prefer longer log from memory
                        if len(str(mem.get("log") or "")) > len(str(data.get("log") or "")):
                            data["log"] = mem["log"]
                            data["progress"] = mem.get("progress") or data.get("progress")
                    _jobs[job_id] = data
                return dict(data)
        except (OSError, json.JSONDecodeError):
            pass
    return get_job(job_id)


def _kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def cancel_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise FileNotFoundError("NOT_FOUND")
    if job.get("status") not in ("queued", "running"):
        return job
    child = _children.get(job_id)
    if child and child.pid:
        _kill_tree(child.pid)
    job["status"] = "cancelled"
    job["finishedAt"] = _now()
    job["log"] = (job.get("log") or "") + "\n[cancelled]\n"
    with _lock:
        _jobs[job_id] = job
    _persist(job)
    return job


def delete_job(job_id: str) -> None:
    job = get_job(job_id)
    if job and job.get("status") in ("queued", "running"):
        raise RuntimeError("JOB_ACTIVE")
    with _lock:
        _jobs.pop(job_id, None)
        _children.pop(job_id, None)
    path = _job_path(job_id)
    path.unlink(missing_ok=True)
    (jobs_dir() / f"{job_id}-report.json").unlink(missing_ok=True)


def mark_job_converted(
    job_id: str, template_id: str | None = None
) -> dict[str, Any]:
    """Browser HTML convert finished for one (or the only) pending template."""
    job = get_job(job_id)
    if not job:
        raise FileNotFoundError("NOT_FOUND")
    status = str(job.get("status") or "")
    if status not in ("awaiting_html", "succeeded", "running"):
        raise RuntimeError(f"JOB_NOT_AWAITING_HTML:{status}")

    pending = [str(x) for x in (job.get("pendingConvertIds") or []) if str(x).strip()]
    single = str(job.get("convertTemplateId") or "").strip()
    if single and single not in pending:
        pending.append(single)

    tid = str(template_id or "").strip()
    if not tid and pending:
        tid = pending[0]
    if tid and tid in pending:
        pending = [x for x in pending if x != tid]

    job["pendingConvertIds"] = pending
    if pending:
        job["convertTemplateId"] = pending[0]
        job["needsBrowserConvert"] = True
        # Still generating more packs → keep running; else wait for remaining converts.
        if status != "running":
            job["status"] = "awaiting_html"
        job["log"] = (job.get("log") or "") + (
            f"\n[browser-html] converted {tid or '?'} · remaining={len(pending)}\n"
        )
    else:
        job["convertTemplateId"] = None
        job["needsBrowserConvert"] = False
        job["log"] = (job.get("log") or "") + (
            f"\n[browser-html] convert complete"
            f"{f' ({tid})' if tid else ''} → "
            f"{'still running' if status == 'running' else 'succeeded'}\n"
        )
        if status != "running":
            job["status"] = "succeeded"
            job["finishedAt"] = job.get("finishedAt") or _now()

    with _lock:
        _jobs[job_id] = job
    _persist(job)
    return dict(job)


def _enqueue_browser_converts(job: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    """Queue template ids that need browser PPTX→HTML. Returns newly queued ids."""
    pending = [str(x) for x in (job.get("pendingConvertIds") or []) if str(x).strip()]
    added: list[str] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("needs_browser_convert"):
            continue
        tid = str(r.get("template_id") or "").strip()
        if not tid or tid in pending:
            continue
        pending.append(tid)
        added.append(tid)
        if r.get("pptx"):
            job["pptxPath"] = str(r["pptx"])
    if pending:
        job["pendingConvertIds"] = pending
        job["needsBrowserConvert"] = True
        job["convertTemplateId"] = pending[0]
    return added


def delete_jobs(ids: list[str]) -> dict[str, Any]:
    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for jid in ids:
        try:
            delete_job(jid)
            deleted.append(jid)
        except Exception as e:  # noqa: BLE001
            failed.append({"id": jid, "error": str(e)})
    return {"deleted": deleted, "failed": failed}


def clear_terminal_jobs() -> dict[str, Any]:
    load_recent_from_disk()
    ids = [
        j["id"]
        for j in list_jobs(200)
        if j.get("status") in ("succeeded", "failed", "cancelled")
    ]
    return delete_jobs(ids)


def _append_log(job: dict[str, Any], text: str) -> None:
    job["log"] = (job.get("log") or "") + text
    if len(job["log"]) > 200_000:
        job["log"] = job["log"][-160_000:]
    # crude progress from summary lines
    m = re.search(r"\[summary\].*ok=(\d+).*fail=(\d+)", text)
    if m and job.get("progress"):
        ok = int(m.group(1))
        fail = int(m.group(2))
        total = job["progress"].get("total") or 1
        job["progress"].update(
            {
                "ok": ok,
                "fail": fail,
                "done": min(total, ok + fail),
                "percent": int(round(((ok + fail) / total) * 100)),
            }
        )
    cloned = re.search(r"\[remix-cloned\]\s+id=(\S+)\s+total=(\d+)", text)
    if cloned:
        tid = cloned.group(1)
        total = max(1, int(cloned.group(2)))
        job["templateId"] = tid
        ids = list(job.get("templateIds") or [])
        if tid not in ids:
            ids.append(tid)
            job["templateIds"] = ids
        job["pagesReady"] = list(job.get("pagesReady") or [])
        job["pageTotal"] = total
        if job.get("progress"):
            job["progress"]["total"] = total
            job["progress"]["lastId"] = tid
            job["progress"]["percent"] = max(int(job["progress"].get("percent") or 0), 5)

    page_m = re.search(
        r"\[remix-page\]\s+id=(\S+)\s+file=(\S+)\s+index=(\d+)\s+done=(\d+)\s+total=(\d+)",
        text,
    )
    if page_m:
        tid = page_m.group(1)
        file_rel = page_m.group(2)
        index = int(page_m.group(3))
        done = int(page_m.group(4))
        total = max(1, int(page_m.group(5)))
        job["templateId"] = tid
        ids = list(job.get("templateIds") or [])
        if tid not in ids:
            ids.append(tid)
            job["templateIds"] = ids
        ready = list(job.get("pagesReady") or [])
        entry = {"index": index, "file": file_rel}
        if not any(isinstance(x, dict) and x.get("index") == index for x in ready):
            ready.append(entry)
            ready.sort(key=lambda x: int(x.get("index") or 0))
        job["pagesReady"] = ready
        job["pageTotal"] = total
        if job.get("progress"):
            job["progress"].update(
                {
                    "total": total,
                    "done": min(total, done),
                    "ok": min(total, done),
                    "percent": int(round((done / total) * 100)),
                    "lastId": tid,
                }
            )

    id_m = re.search(r"id=([^\s]+)", text)
    if id_m and job.get("progress"):
        job["progress"]["lastId"] = id_m.group(1)
        job["templateId"] = job.get("templateId") or id_m.group(1)
        ids = list(job.get("templateIds") or [])
        if id_m.group(1) not in ids:
            ids.append(id_m.group(1))
            job["templateIds"] = ids


def _spawn(job: dict[str, Any], args: list[str], extra_env: dict[str, str]) -> dict[str, Any]:
    cmd = _backend_bin()
    if not cmd.is_file():
        raise RuntimeError(
            f"未找到 webppt-backend：{cmd}。请先在 backend/ 下创建 venv 并 pip install -e ."
        )
    env = {**os.environ, "PYTHONUNBUFFERED": "1", **extra_env}
    job["status"] = "running"
    job["startedAt"] = _now()
    job["log"] = (job.get("log") or "") + (
        "$ webppt-backend "
        + " ".join(json.dumps(a) if re.search(r"\s", a) else a for a in args)
        + "\n"
    )
    with _lock:
        _jobs[job["id"]] = job
    _persist(job)

    child = subprocess.Popen(
        [str(cmd), *args],
        cwd=str(repo_root() / "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _children[job["id"]] = child

    def reader() -> None:
        assert child.stdout is not None
        for line in iter(child.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace")
            with _lock:
                cur = _jobs.get(job["id"]) or job
                if cur.get("status") == "cancelled":
                    break
                _append_log(cur, text)
                _jobs[job["id"]] = cur
                _persist(cur)
        code = child.wait()
        with _lock:
            cur = _jobs.get(job["id"]) or job
            if cur.get("status") == "cancelled":
                return
            cur["exitCode"] = code
            cur["finishedAt"] = _now()
            if code == 0:
                cur["status"] = "succeeded"
                if cur.get("progress"):
                    total = cur["progress"].get("total") or 1
                    cur["progress"]["done"] = total
                    cur["progress"]["ok"] = max(cur["progress"].get("ok") or 0, 1)
                    cur["progress"]["percent"] = 100
            else:
                cur["status"] = "failed"
                cur["error"] = _error_from_log(
                    cur.get("log"),
                    str(cur.get("error") or f"exit {code}"),
                )
            # read report for template ids / browser convert flags
            report = jobs_dir() / f"{cur['id']}-report.json"
            upsert_ids: list[str] = []
            if report.is_file():
                try:
                    rows = json.loads(report.read_text(encoding="utf-8"))
                    if isinstance(rows, list):
                        ids = [
                            r.get("template_id")
                            for r in rows
                            if isinstance(r, dict) and r.get("template_id")
                        ]
                        if ids:
                            cur["templateIds"] = ids
                            cur["templateId"] = ids[0]
                        dict_rows = [r for r in rows if isinstance(r, dict)]
                        for r in dict_rows:
                            tid = r.get("template_id")
                            # 成功完整包立即入库；需浏览器转 HTML 的 stub 也入库（页数 0，等转换）
                            if tid and r.get("ok"):
                                upsert_ids.append(str(tid))
                        added = _enqueue_browser_converts(cur, dict_rows)
                        if code == 0 and added:
                            cur["status"] = "awaiting_html"
                            _append_log(
                                cur,
                                f"[browser-html] queued: {', '.join(added)}\n",
                            )
                except (OSError, json.JSONDecodeError):
                    pass
            _jobs[cur["id"]] = cur
            _persist(cur)
            _children.pop(cur["id"], None)
            # 每包成功即入库（整批部分失败时成功包仍进待审核）
            # 首页 gallery remix / 编辑器对话写 sessions 或不入库
            if (
                upsert_ids
                and not cur.get("gallery")
                and not cur.get("editor")
            ):
                try:
                    from admin.store import upsert_template_row

                    for tid in upsert_ids:
                        upsert_template_row(tid)
                except Exception:
                    pass

    threading.Thread(target=reader, daemon=True).start()
    return job


def _build_ppt_master_args(
    *,
    count: int,
    pages: int,
    visual_style: str,
    style_intent: str,
    ensure_style: bool,
    mock: bool,
    skip_image: bool,
    palette_refine: bool,
    quality_gate: str,
    svg_repair: bool,
    strip_unsupported: bool,
    report_path: Path,
    hint: str,
) -> list[str]:
    args = [
        "ppt-master",
        "--count",
        str(count),
        "--pages",
        str(pages),
        "--style",
        visual_style,
        "--out-root",
        str(templates_root()),
        "--report",
        str(report_path),
        "--slide-concurrency",
        "3",
    ]
    if ensure_style:
        args.append("--ensure-style")
    if style_intent:
        args.extend(["--style-intent", style_intent])
    if mock:
        args.append("--mock")
    if skip_image:
        args.append("--skip-image")
    else:
        args.append("--with-images")
    args.append("--palette-refine" if palette_refine else "--no-palette-refine")
    args.extend(["--quality-gate", quality_gate])
    args.append("--svg-repair" if svg_repair else "--no-svg-repair")
    args.append(
        "--strip-unsupported" if strip_unsupported else "--no-strip-unsupported"
    )
    args.extend(["--", hint])
    return args


def _pick_pack_random(
    *,
    reroll_theme: bool,
    reroll_style: bool,
    random_style_mode: str,
    used_styles: list[str],
    fallback_style: str,
    fallback_intent: str,
    fallback_ensure: bool,
    fallback_prompt: str,
    mock: bool,
) -> tuple[str, str, bool, str]:
    """Return (visual_style, style_intent, ensure_style, prompt) for one pack."""
    visual_style = fallback_style
    style_intent = fallback_intent
    ensure_style = fallback_ensure
    prompt = fallback_prompt

    if reroll_style:
        if random_style_mode == "invent":
            if mock:
                style_intent = f"mock invent style {uuid.uuid4().hex[:6]}"
                ensure_style = True
                visual_style = fallback_style or "dark-tech"
            else:
                from admin.score_vl import generate_random_style_intent

                data = generate_random_style_intent()
                style_intent = str(data.get("styleIntent") or "").strip()
                ensure_style = data.get("ensureStyle") is not False
                visual_style = fallback_style or "dark-tech"
        else:
            from admin.styles_catalog import pick_random

            picked = pick_random(exclude=list(used_styles))
            if not picked:
                picked = pick_random(exclude=[])
            if not picked:
                raise RuntimeError("风格目录为空，无法随机")
            visual_style = str(picked.get("styleId") or "").strip() or fallback_style
            used_styles.append(visual_style)
            style_intent = ""
            ensure_style = False

    if reroll_theme:
        if mock:
            prompt = f"Mock 随机主题 {uuid.uuid4().hex[:6]}：虚构产品发布会"
        else:
            from admin.score_vl import generate_random_theme_prompt

            theme = generate_random_theme_prompt(
                visual_style="" if style_intent else visual_style
            )
            prompt = str(theme.get("prompt") or "").strip() or fallback_prompt

    return visual_style, style_intent, ensure_style, prompt


def _spawn_per_pack_random(
    job: dict[str, Any],
    *,
    base_extra: dict[str, str],
    pages: int,
    mock: bool,
    skip_image: bool,
    palette_refine: bool,
    quality_gate: str,
    svg_repair: bool,
    strip_unsupported: bool,
    reroll_theme: bool,
    reroll_style: bool,
    random_style_mode: str,
    fallback_style: str,
    fallback_intent: str,
    fallback_ensure: bool,
    fallback_prompt: str,
) -> dict[str, Any]:
    """One job · N packs：按需每包重随主题/风格后串行跑 ppt-master --count 1。"""
    cmd = _backend_bin()
    if not cmd.is_file():
        raise RuntimeError(
            f"未找到 webppt-backend：{cmd}。请先在 backend/ 下创建 venv 并 pip install -e ."
        )

    total = int(job.get("count") or 1)
    job["status"] = "running"
    job["startedAt"] = _now()
    job["log"] = (job.get("log") or "") + (
        f"[random] per-pack · theme_reroll={reroll_theme} style_reroll={reroll_style} "
        f"mode={random_style_mode} ×{total}\n"
    )
    with _lock:
        _jobs[job["id"]] = job
    _persist(job)

    def runner() -> None:
        used_styles: list[str] = []
        all_rows: list[dict[str, Any]] = []
        ok = fail = 0
        for i in range(1, total + 1):
            with _lock:
                cur = _jobs.get(job["id"]) or job
                if cur.get("status") == "cancelled":
                    return
            try:
                style, intent, ensure, prompt = _pick_pack_random(
                    reroll_theme=reroll_theme,
                    reroll_style=reroll_style,
                    random_style_mode=random_style_mode,
                    used_styles=used_styles,
                    fallback_style=fallback_style,
                    fallback_intent=fallback_intent,
                    fallback_ensure=fallback_ensure,
                    fallback_prompt=fallback_prompt,
                    mock=mock,
                )
            except Exception as e:  # noqa: BLE001
                fail += 1
                with _lock:
                    cur = _jobs.get(job["id"]) or job
                    _append_log(cur, f"[pack {i}/{total}] random FAIL: {e}\n")
                    if cur.get("progress"):
                        cur["progress"].update(
                            {
                                "ok": ok,
                                "fail": fail,
                                "done": ok + fail,
                                "percent": int(round(((ok + fail) / total) * 100)),
                            }
                        )
                    _jobs[job["id"]] = cur
                    _persist(cur)
                continue

            pack_report = jobs_dir() / f"{job['id']}-pack{i}-report.json"
            args = _build_ppt_master_args(
                count=1,
                pages=pages,
                visual_style=style,
                style_intent=intent,
                ensure_style=ensure,
                mock=mock,
                skip_image=skip_image,
                palette_refine=palette_refine,
                quality_gate=quality_gate,
                svg_repair=svg_repair,
                strip_unsupported=strip_unsupported,
                report_path=pack_report,
                hint=prompt,
            )
            extra = dict(base_extra)
            from templates.categories import normalize_category

            category = normalize_category(style)
            if category:
                extra["AGENT_TEMPLATE_CATEGORY"] = category

            with _lock:
                cur = _jobs.get(job["id"]) or job
                label = intent or style
                _append_log(
                    cur,
                    f"\n[pack {i}/{total}] style={label}\nprompt={prompt[:80]}…\n"
                    if len(prompt) > 80
                    else f"\n[pack {i}/{total}] style={label}\nprompt={prompt}\n",
                )
                cur["visualStyle"] = style
                if intent:
                    cur["styleIntent"] = intent
                cur["prompt"] = prompt
                if category:
                    cur["category"] = category
                _jobs[job["id"]] = cur
                _persist(cur)

            env = {**os.environ, "PYTHONUNBUFFERED": "1", **extra}
            child = subprocess.Popen(
                [str(cmd), *args],
                cwd=str(repo_root() / "backend"),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            _children[job["id"]] = child
            assert child.stdout is not None
            for line in iter(child.stdout.readline, b""):
                text = line.decode("utf-8", errors="replace")
                with _lock:
                    cur = _jobs.get(job["id"]) or job
                    if cur.get("status") == "cancelled":
                        break
                    _append_log(cur, text)
                    _jobs[job["id"]] = cur
                    _persist(cur)
            code = child.wait()
            _children.pop(job["id"], None)

            with _lock:
                cur = _jobs.get(job["id"]) or job
                if cur.get("status") == "cancelled":
                    return

            pack_ok = code == 0
            pack_tids: list[str] = []
            pack_rows: list[dict[str, Any]] = []
            if pack_report.is_file():
                try:
                    rows = json.loads(pack_report.read_text(encoding="utf-8"))
                    if isinstance(rows, list):
                        pack_rows = [r for r in rows if isinstance(r, dict)]
                        all_rows.extend(pack_rows)
                        for r in pack_rows:
                            if r.get("template_id"):
                                tid = str(r["template_id"])
                                pack_tids.append(tid)
                                with _lock:
                                    cur = _jobs.get(job["id"]) or job
                                    ids = list(cur.get("templateIds") or [])
                                    if tid not in ids:
                                        ids.append(tid)
                                        cur["templateIds"] = ids
                                    cur["templateId"] = cur.get("templateId") or tid
                                    if cur.get("progress"):
                                        cur["progress"]["lastId"] = tid
                                    _jobs[job["id"]] = cur
                except (OSError, json.JSONDecodeError):
                    pass
            if pack_ok:
                ok += 1
                # 每包成功即入库，并立刻把需浏览器转 HTML 的包排队（前端边生成边转）
                try:
                    from admin.store import upsert_template_row

                    for tid in pack_tids:
                        upsert_template_row(tid)
                except Exception:
                    pass
                with _lock:
                    cur = _jobs.get(job["id"]) or job
                    added = _enqueue_browser_converts(cur, pack_rows)
                    if added:
                        _append_log(
                            cur,
                            f"[browser-html] queued now: {', '.join(added)}\n",
                        )
                    _jobs[job["id"]] = cur
                    _persist(cur)
            else:
                fail += 1
            with _lock:
                cur = _jobs.get(job["id"]) or job
                if cur.get("progress"):
                    cur["progress"].update(
                        {
                            "ok": ok,
                            "fail": fail,
                            "done": ok + fail,
                            "percent": int(round(((ok + fail) / total) * 100)),
                        }
                    )
                _append_log(
                    cur,
                    f"[pack {i}/{total}] {'ok' if pack_ok else f'fail exit={code}'}\n",
                )
                _jobs[job["id"]] = cur
                _persist(cur)

        report_path = jobs_dir() / f"{job['id']}-report.json"
        try:
            report_path.write_text(
                json.dumps(all_rows, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        with _lock:
            cur = _jobs.get(job["id"]) or job
            if cur.get("status") == "cancelled":
                return
            cur["finishedAt"] = _now()
            cur["exitCode"] = 0 if fail == 0 and ok > 0 else 1
            # Catch any convert flags missed mid-flight
            _enqueue_browser_converts(cur, all_rows)
            pending = [
                str(x)
                for x in (cur.get("pendingConvertIds") or [])
                if str(x).strip()
            ]
            if fail == 0 and ok > 0:
                if pending:
                    cur["status"] = "awaiting_html"
                    cur["needsBrowserConvert"] = True
                    cur["convertTemplateId"] = pending[0]
                    if cur.get("progress"):
                        cur["progress"]["done"] = total
                        cur["progress"]["percent"] = 100
                else:
                    cur["status"] = "succeeded"
                    if cur.get("progress"):
                        cur["progress"]["done"] = total
                        cur["progress"]["percent"] = 100
            else:
                cur["status"] = "failed"
                cur["error"] = _error_from_log(
                    cur.get("log"),
                    str(cur.get("error") or f"ok={ok} fail={fail}"),
                )
            _append_log(cur, f"[summary] ok={ok} fail={fail}\n")
            _jobs[cur["id"]] = cur
            _persist(cur)
    threading.Thread(target=runner, daemon=True).start()
    return job


def start_generate_job(options: dict[str, Any]) -> dict[str, Any]:
    count = max(1, min(20, int(options.get("count") or 1)))
    pages = int(options.get("pages") or 7)
    pages = min(12, max(3, pages))
    visual_style = (options.get("visualStyle") or "dark-tech").strip() or "dark-tech"
    style_intent = (options.get("styleIntent") or "").strip()
    ensure_style = bool(options.get("ensureStyle"))
    quality_gate = str(options.get("qualityGate") or "soft").strip().lower()
    if quality_gate not in ("soft", "strict", "skip"):
        quality_gate = "soft"
    svg_repair = options.get("repairOnFail") is not False
    strip_unsupported = options.get("stripUnsupported") is not False
    palette_refine = bool(options.get("paletteRefine"))
    # Per-job DeepSeek / Gemini thinking; default off (long reasoning is expensive).
    llm_thinking = bool(options.get("llmThinking"))
    hint = (options.get("prompt") or "").strip() or (
        "虚构 AI 产品发布会：冲击力封面、章节页、能力页、数据页、收尾；禁止说明书式排版。"
    )
    mock = bool(options.get("mock"))
    skip_image = bool(options.get("skipImage"))
    random_theme = bool(options.get("randomTheme"))
    random_style = bool(options.get("randomStyle"))
    random_style_mode = str(options.get("randomStyleMode") or "catalog").strip() or "catalog"

    def _flag(name: str, legacy: str | None = None, default: bool = True) -> bool:
        raw = options.get(name)
        if raw is None and legacy:
            raw = options.get(legacy)
        if raw is None:
            return default
        return bool(raw)

    # 默认整批共用；显式 false 且 count>1 时该项每包重随
    reuse_theme = _flag("reuseRandomTheme", "reuseRandom", True)
    reuse_style = _flag("reuseRandomStyle", "reuseRandom", True)
    reroll_theme = count > 1 and random_theme and not reuse_theme
    reroll_style = count > 1 and random_style and not reuse_style
    per_pack_random = reroll_theme or reroll_style

    llm = resolve_llm_selection(options.get("llmProvider"), options.get("llmModel"))
    image = resolve_image_selection(options.get("imageProvider"), options.get("imageModel"))

    skill = repo_root() / "ppt-master" / "skills" / "ppt-master" / "SKILL.md"
    if not skill.is_file():
        raise RuntimeError(f"未找到 PPT Master Skill：{skill}")

    if not mock:
        llm_env_for_dual(llm)
        if not skip_image:
            image_env_for_selection(image)

    job_id = uuid.uuid4().hex[:12]
    report_path = jobs_dir() / f"{job_id}-report.json"
    job: dict[str, Any] = {
        "id": job_id,
        "prompt": hint,
        "mock": mock,
        "skipImage": skip_image,
        "paletteRefine": palette_refine,
        "packageFormat": "ppt-master",
        "pipeline": "ppt-master",
        "visualStyle": visual_style,
        "styleIntent": style_intent or None,
        "ensureStyle": ensure_style,
        "randomTheme": random_theme or None,
        "randomStyle": random_style or None,
        "randomStyleMode": random_style_mode if random_style else None,
        "reuseRandomTheme": reuse_theme if random_theme else None,
        "reuseRandomStyle": reuse_style if random_style else None,
        "pptMasterRender": "svg",
        "repairOnFail": svg_repair,
        "qualityGate": quality_gate,
        "stripUnsupported": strip_unsupported,
        "llmThinking": llm_thinking,
        "count": count,
        "pages": pages,
        "llmProvider": llm["provider"],
        "llmModel": llm["model"],
        "llmLabel": llm["label"],
        "imageProvider": image["provider"],
        "imageModel": image["model"],
        "imageLabel": image["label"],
        "status": "queued",
        "createdAt": _now(),
        "outputDir": str(templates_root()),
        "log": "",
        "progress": _initial_progress(count),
    }

    extra: dict[str, str] = {}
    if mock:
        extra["AGENT_MOCK"] = "1"
    if skip_image:
        extra["AGENT_SKIP_IMAGE"] = "1"
    extra["AGENT_PALETTE_REFINE"] = "1" if palette_refine else "0"
    # Always set so job env overrides leftover shell/export defaults.
    extra["LLM_THINKING"] = "1" if llm_thinking else "0"
    from templates.categories import normalize_category

    # 类型 = 视觉风格；允许 options.category 覆盖
    category_raw = str(options.get("category") or visual_style or "").strip()
    if category_raw and category_raw != "auto":
        category = normalize_category(category_raw)
        if category:
            extra["AGENT_TEMPLATE_CATEGORY"] = category
            job["category"] = category
    if not mock:
        extra.update(llm_env_for_dual(llm))
        if not skip_image:
            extra.update(image_env_for_selection(image))

    if per_pack_random or count > 1:
        job["log"] += (
            f"[pipeline] ppt-master · serial packs ×{count} "
            f"(theme_reroll={reroll_theme} style_reroll={reroll_style}; "
            "each pack can browser-convert immediately)\n"
        )
        return _spawn_per_pack_random(
            job,
            base_extra=extra,
            pages=pages,
            mock=mock,
            skip_image=skip_image,
            palette_refine=palette_refine,
            quality_gate=quality_gate,
            svg_repair=svg_repair,
            strip_unsupported=strip_unsupported,
            reroll_theme=reroll_theme,
            reroll_style=reroll_style,
            random_style_mode=random_style_mode,
            fallback_style=visual_style,
            fallback_intent=style_intent,
            fallback_ensure=ensure_style,
            fallback_prompt=hint,
        )

    args = _build_ppt_master_args(
        count=count,
        pages=pages,
        visual_style=visual_style,
        style_intent=style_intent,
        ensure_style=ensure_style,
        mock=mock,
        skip_image=skip_image,
        palette_refine=palette_refine,
        quality_gate=quality_gate,
        svg_repair=svg_repair,
        strip_unsupported=strip_unsupported,
        report_path=report_path,
        hint=hint,
    )

    job["log"] += f"[pipeline] ppt-master\n[style] {visual_style}\n"
    return _spawn(job, args, extra)


def start_remix_job(options: dict[str, Any]) -> dict[str, Any]:
    source_id = str(options.get("sourceTemplateId") or "").strip()
    if not source_id:
        raise RuntimeError("缺少源模板 id")
    hint = (options.get("prompt") or "").strip()
    if not hint:
        raise RuntimeError("请填写内容要求")
    source = templates_root() / source_id
    if not (source / "template.json").is_file():
        raise RuntimeError(f"源模板不存在：{source_id}")
    spec = source / "visual-spec.md"
    if not spec.is_file() or not spec.read_text(encoding="utf-8").strip():
        raise RuntimeError("源模板缺少 visual-spec.md，请先生成设计规范后再使用模板")

    mock = bool(options.get("mock"))
    skip_image = options.get("skipImage") is not False
    gallery = bool(options.get("gallery"))
    # 首页 remix → workspace/；Admin「使用模板」仍写模板库目录
    out_root = workspace_root() if gallery else templates_root()
    if gallery:
        try:
            cleanup_expired_sessions()
        except Exception:
            pass
    llm = resolve_llm_selection(options.get("llmProvider"), options.get("llmModel"))
    image = resolve_image_selection(options.get("imageProvider"), options.get("imageModel"))
    if not mock:
        llm_env_for_dual(llm)
        if not skip_image:
            image_env_for_selection(image)

    job_id = uuid.uuid4().hex[:12]
    report_path = jobs_dir() / f"{job_id}-report.json"
    job: dict[str, Any] = {
        "id": job_id,
        "prompt": hint,
        "mock": mock,
        "skipImage": skip_image,
        "packageFormat": "ppt-master",
        "pipeline": "ppt-master",
        "sourceTemplateId": source_id,
        "count": 1,
        "llmProvider": llm["provider"],
        "llmModel": llm["model"],
        "llmLabel": llm["label"],
        "imageProvider": image["provider"],
        "imageModel": image["model"],
        "imageLabel": image["label"],
        "status": "queued",
        "createdAt": _now(),
        "outputDir": str(out_root),
        "log": "",
        "progress": _initial_progress(1),
    }
    args = [
        "remix-template",
        source_id,
        "--out-root",
        str(out_root),
        "--report",
        str(report_path),
        "--prompt",
        hint,
    ]
    if gallery:
        args.append("--ephemeral")
    if mock:
        args.append("--mock")
    if skip_image:
        args.append("--skip-image")
    else:
        args.append("--with-images")
    status = str(options.get("status") or "pending").strip().lower()
    if status in {"pending", "approved"}:
        args.extend(["--status", status])

    extra: dict[str, str] = {}
    if mock:
        extra["AGENT_MOCK"] = "1"
    if not mock:
        extra.update(llm_env_for_dual(llm))
        if not skip_image:
            extra.update(image_env_for_selection(image))
    job["log"] += (
        f"[remix] source={source_id}"
        + (" out=sessions (ephemeral)\n" if gallery else "\n")
    )
    job["gallery"] = gallery
    return _spawn(job, args, extra)


def start_rewrite_page_job(options: dict[str, Any]) -> dict[str, Any]:
    from admin.fsutil import template_dir as resolve_pack

    source_id = str(options.get("sourceTemplateId") or options.get("templateId") or "").strip()
    if not source_id:
        raise RuntimeError("缺少模板 id")
    issue = (options.get("issue") or options.get("prompt") or "").strip()
    if len(issue) < 4:
        raise RuntimeError("请填写本页问题（至少 4 字）")
    if len(issue) > 2000:
        raise RuntimeError("问题描述过长（最多 2000 字）")

    source = resolve_pack(source_id)
    meta_path = source / "template.json"
    if not meta_path.is_file():
        raise RuntimeError(f"源模板不存在：{source_id}")

    slide_file = str(options.get("file") or options.get("slideFile") or "").strip()
    page_index = options.get("pageIndex")
    if page_index is not None and page_index != "":
        try:
            page_index = int(page_index)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("pageIndex 必须是整数") from exc
    else:
        page_index = None
    if not slide_file and page_index is None:
        raise RuntimeError("缺少 file 或 pageIndex")

    # Validate slides exist before spawning
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 template.json：{exc}") from exc
    slides = meta.get("slides") if isinstance(meta, dict) else None
    if not isinstance(slides, list) or not slides:
        raise RuntimeError("模板尚无 HTML 页面，请先完成 PPTX→HTML 转换")

    mock = bool(options.get("mock"))
    llm = resolve_llm_selection(options.get("llmProvider"), options.get("llmModel"))
    if not mock:
        llm_env_for_dual(llm)

    job_id = uuid.uuid4().hex[:12]
    report_path = jobs_dir() / f"{job_id}-report.json"
    job: dict[str, Any] = {
        "id": job_id,
        "prompt": issue,
        "issue": issue,
        "mock": mock,
        "skipImage": True,
        "packageFormat": "ppt-master",
        "pipeline": "rewrite-page",
        "sourceTemplateId": source_id,
        "templateId": source_id,
        "slideFile": slide_file or None,
        "pageIndex": page_index,
        "count": 1,
        "llmProvider": llm["provider"],
        "llmModel": llm["model"],
        "llmLabel": llm["label"],
        "status": "queued",
        "createdAt": _now(),
        "outputDir": str(templates_root()),
        "log": "",
        "progress": _initial_progress(1),
    }
    args = [
        "rewrite-page",
        source_id,
        "--issue",
        issue,
        "--report",
        str(report_path),
    ]
    if slide_file:
        args.extend(["--file", slide_file])
    if page_index is not None:
        args.extend(["--page-index", str(page_index)])
    if mock:
        args.append("--mock")

    extra: dict[str, str] = {}
    if mock:
        extra["AGENT_MOCK"] = "1"
    else:
        extra.update(llm_env_for_dual(llm))
        # Prefer off for rewrite jobs unless explicitly enabled in shell
        extra.setdefault("LLM_THINKING", "0")
    job["log"] += (
        f"[rewrite-page] template={source_id} "
        f"file={slide_file or '-'} pageIndex={page_index if page_index is not None else '-'}\n"
    )
    if options.get("editor"):
        job["editor"] = True
    return _spawn(job, args, extra)


def start_generate_page_job(options: dict[str, Any]) -> dict[str, Any]:
    from admin.fsutil import template_dir as resolve_pack

    source_id = str(options.get("sourceTemplateId") or options.get("templateId") or "").strip()
    if not source_id:
        raise RuntimeError("缺少模板 id")
    issue = (options.get("issue") or options.get("prompt") or "").strip()
    if len(issue) < 4:
        raise RuntimeError("请填写新页要求（至少 4 字）")
    if len(issue) > 2000:
        raise RuntimeError("问题描述过长（最多 2000 字）")

    source = resolve_pack(source_id)
    meta_path = source / "template.json"
    if not meta_path.is_file():
        raise RuntimeError(f"源模板不存在：{source_id}")

    after_file = str(options.get("afterFile") or options.get("file") or "").strip() or None
    after_page_index = options.get("afterPageIndex")
    if after_page_index is None:
        after_page_index = options.get("pageIndex")
    if after_page_index is not None and after_page_index != "":
        try:
            after_page_index = int(after_page_index)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("afterPageIndex 必须是整数") from exc
    else:
        after_page_index = None

    title_hint = str(options.get("titleHint") or options.get("title") or "").strip() or None
    mock = bool(options.get("mock"))
    llm = resolve_llm_selection(options.get("llmProvider"), options.get("llmModel"))
    image = resolve_image_selection(options.get("imageProvider"), options.get("imageModel"))
    if not mock:
        llm_env_for_dual(llm)

    job_id = uuid.uuid4().hex[:12]
    report_path = jobs_dir() / f"{job_id}-report.json"
    job: dict[str, Any] = {
        "id": job_id,
        "prompt": issue,
        "issue": issue,
        "mock": mock,
        "skipImage": True,
        "packageFormat": "ppt-master",
        "pipeline": "generate-page",
        "sourceTemplateId": source_id,
        "templateId": source_id,
        "afterFile": after_file,
        "afterPageIndex": after_page_index,
        "titleHint": title_hint,
        "count": 1,
        "llmProvider": llm["provider"],
        "llmModel": llm["model"],
        "llmLabel": llm["label"],
        "imageProvider": image["provider"],
        "imageModel": image["model"],
        "imageLabel": image["label"],
        "status": "queued",
        "createdAt": _now(),
        "outputDir": str(templates_root()),
        "log": "",
        "progress": _initial_progress(1),
        "editor": True,
    }
    args = [
        "generate-page",
        source_id,
        "--issue",
        issue,
        "--report",
        str(report_path),
    ]
    if after_file:
        args.extend(["--after-file", after_file])
    if after_page_index is not None:
        args.extend(["--after-page-index", str(after_page_index)])
    if title_hint:
        args.extend(["--title-hint", title_hint])
    if mock:
        args.append("--mock")

    extra: dict[str, str] = {}
    if mock:
        extra["AGENT_MOCK"] = "1"
    else:
        extra.update(llm_env_for_dual(llm))
        extra.setdefault("LLM_THINKING", "0")
    job["log"] += (
        f"[generate-page] template={source_id} "
        f"afterFile={after_file or '-'} afterPageIndex="
        f"{after_page_index if after_page_index is not None else '-'}\n"
    )
    return _spawn(job, args, extra)


def start_delete_page_job(options: dict[str, Any]) -> dict[str, Any]:
    """Queue a delete-page CLI job (fast; kept async for uniform editor polling)."""
    from admin.fsutil import template_dir as resolve_pack

    source_id = str(options.get("sourceTemplateId") or options.get("templateId") or "").strip()
    if not source_id:
        raise RuntimeError("缺少模板 id")

    source = resolve_pack(source_id)
    meta_path = source / "template.json"
    if not meta_path.is_file():
        raise RuntimeError(f"源模板不存在：{source_id}")

    slide_file = str(options.get("file") or options.get("slideFile") or "").strip()
    page_index = options.get("pageIndex")
    if page_index is not None and page_index != "":
        try:
            page_index = int(page_index)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("pageIndex 必须是整数") from exc
    else:
        page_index = None
    if not slide_file and page_index is None:
        raise RuntimeError("缺少 file 或 pageIndex")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 template.json：{exc}") from exc
    slides = meta.get("slides") if isinstance(meta, dict) else None
    if not isinstance(slides, list) or len(slides) <= 1:
        raise RuntimeError("至少保留一页，无法删除")

    job_id = uuid.uuid4().hex[:12]
    report_path = jobs_dir() / f"{job_id}-report.json"
    job: dict[str, Any] = {
        "id": job_id,
        "prompt": f"delete {slide_file or page_index}",
        "issue": f"delete {slide_file or page_index}",
        "mock": False,
        "skipImage": True,
        "packageFormat": "ppt-master",
        "pipeline": "delete-page",
        "sourceTemplateId": source_id,
        "templateId": source_id,
        "slideFile": slide_file or None,
        "pageIndex": page_index,
        "count": 1,
        "status": "queued",
        "createdAt": _now(),
        "outputDir": str(source),
        "log": "",
        "progress": _initial_progress(1),
        "editor": True,
    }
    args = [
        "delete-page",
        source_id,
        "--report",
        str(report_path),
    ]
    if slide_file:
        args.extend(["--file", slide_file])
    if page_index is not None:
        args.extend(["--page-index", str(page_index)])
    job["log"] += (
        f"[delete-page] template={source_id} "
        f"file={slide_file or '-'} pageIndex={page_index if page_index is not None else '-'}\n"
    )
    return _spawn(job, args, extra={})


def start_editor_assist_job(options: dict[str, Any]) -> dict[str, Any]:
    """Plan + execute editor assist actions (modify / image regen / add / delete)."""
    from admin.fsutil import template_dir as resolve_pack

    source_id = str(options.get("sourceTemplateId") or options.get("templateId") or "").strip()
    if not source_id:
        raise RuntimeError("缺少模板 id")
    issue = (options.get("issue") or options.get("prompt") or "").strip()
    if len(issue) < 4:
        raise RuntimeError("请填写指令（至少 4 字）")
    if len(issue) > 2000:
        raise RuntimeError("问题描述过长（最多 2000 字）")

    source = resolve_pack(source_id)
    meta_path = source / "template.json"
    if not meta_path.is_file():
        raise RuntimeError(f"源模板不存在：{source_id}")

    slide_file = str(options.get("file") or options.get("slideFile") or "").strip()
    page_index = options.get("pageIndex")
    if page_index is not None and page_index != "":
        try:
            page_index = int(page_index)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("pageIndex 必须是整数") from exc
    else:
        page_index = None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 template.json：{exc}") from exc
    slides = meta.get("slides") if isinstance(meta, dict) else None
    if not isinstance(slides, list) or not slides:
        raise RuntimeError("模板尚无 HTML 页面")

    mock = bool(options.get("mock"))
    llm = resolve_llm_selection(options.get("llmProvider"), options.get("llmModel"))
    if not mock:
        llm_env_for_dual(llm)

    image_env: dict[str, str] = {}
    try:
        img = resolve_image_selection(
            options.get("imageProvider"), options.get("imageModel")
        )
        image_env = image_env_for_selection(img)
    except Exception:
        # Image provider optional until regenerate_image runs; regen will warn/placeholder.
        image_env = {}

    job_id = uuid.uuid4().hex[:12]
    report_path = jobs_dir() / f"{job_id}-report.json"
    target_path = None
    target = options.get("element") or options.get("targetElement")
    if target:
        target_path = jobs_dir() / f"{job_id}-target.json"
        try:
            from templates.element_target import normalize_element_target

            cleaned = normalize_element_target(target)
            if cleaned:
                target_path.write_text(
                    json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            else:
                target_path = None
        except Exception:
            target_path = None

    job: dict[str, Any] = {
        "id": job_id,
        "prompt": issue,
        "issue": issue,
        "mock": mock,
        "skipImage": False,
        "packageFormat": "ppt-master",
        "pipeline": "editor-assist",
        "sourceTemplateId": source_id,
        "templateId": source_id,
        "slideFile": slide_file or None,
        "pageIndex": page_index,
        "count": 1,
        "llmProvider": llm["provider"],
        "llmModel": llm["model"],
        "llmLabel": llm["label"],
        "status": "queued",
        "createdAt": _now(),
        "outputDir": str(source),
        "log": "",
        "progress": _initial_progress(1),
        "editor": True,
    }
    args = [
        "editor-assist",
        source_id,
        "--issue",
        issue,
        "--report",
        str(report_path),
    ]
    if slide_file:
        args.extend(["--file", slide_file])
    if page_index is not None:
        args.extend(["--page-index", str(page_index)])
    if target_path is not None:
        args.extend(["--target-json", str(target_path)])
    if mock:
        args.append("--mock")

    extra: dict[str, str] = {}
    if mock:
        extra["AGENT_MOCK"] = "1"
    else:
        extra.update(llm_env_for_dual(llm))
        extra.setdefault("LLM_THINKING", "0")
        extra.update(image_env)
        # Allow image regen even if AGENT_SKIP_IMAGE was set in parent shell
        extra["AGENT_SKIP_IMAGE"] = "0"
    job["log"] += (
        f"[editor-assist] template={source_id} "
        f"file={slide_file or '-'} pageIndex={page_index if page_index is not None else '-'}\n"
    )
    return _spawn(job, args, extra)
