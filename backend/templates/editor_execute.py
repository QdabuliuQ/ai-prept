"""Execute a planned list of editor assist actions serially."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from templates.editor_plan import (
    OP_ADD,
    OP_DELETE,
    OP_MODIFY,
    OP_REGENERATE_IMAGE,
    plan_editor_actions,
)
from templates.page_delete import run_page_delete
from templates.page_generate import run_page_generate
from templates.page_image_regen import run_page_image_regen
from templates.page_rewrite import _load_meta, run_page_rewrite

LogFn = Callable[[str], None]


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg if msg.endswith("\n") else msg + "\n")


def _slide_outline(meta: dict[str, Any]) -> list[dict[str, Any]]:
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    out: list[dict[str, Any]] = []
    for item in slides:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "file": str(item.get("file") or ""),
                "title": str(item.get("title") or ""),
            }
        )
    return out


def _build_summary_markdown(
    *,
    plan_summary: str,
    issue: str,
    results: list[dict[str, Any]],
) -> str:
    lines = ["### 本次操作总结", ""]
    if plan_summary:
        lines.append(f"- **计划**：{plan_summary}")
    lines.append(f"- **你的要求**：{issue}")
    lines.append("")
    lines.append("#### 已执行")
    if not results:
        lines.append("- （无）")
    for i, row in enumerate(results, 1):
        op = str(row.get("op") or row.get("pipeline") or "action")
        ok = row.get("ok", True)
        mark = "✓" if ok else "✗"
        detail = row.get("file") or row.get("error") or ""
        extra = ""
        imgs = row.get("regeneratedImages") or []
        if imgs:
            extra = f" · 图：{', '.join(str(x) for x in imgs)}"
        if row.get("insertAt") is not None:
            extra += f" · 插入位置第 {int(row['insertAt']) + 1} 页"
        lines.append(f"{i}. {mark} **{op}** {detail}{extra}".rstrip())
    failed = [r for r in results if not r.get("ok", True)]
    lines.append("")
    if failed:
        lines.append(f"- **结果**：部分失败（{len(failed)}）")
    else:
        lines.append("- **结果**：已写回当前临时稿")
    return "\n".join(lines)


def run_editor_assist(
    package: str | Path,
    *,
    issue: str,
    slide_file: str | None = None,
    page_index: int | None = None,
    mock: bool | None = None,
    target_element: dict[str, Any] | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    """Plan + execute editor actions; return aggregated report row."""
    from templates.element_target import (
        format_target_for_prompt,
        image_filename_from_target,
        normalize_element_target,
    )

    package_dir = Path(package).expanduser().resolve()
    if not package_dir.is_dir():
        raise RuntimeError(f"模板目录不存在：{package_dir}")
    issue = (issue or "").strip()
    if len(issue) < 4:
        raise RuntimeError("指令太短")
    if len(issue) > 2000:
        raise RuntimeError("指令过长（最多 2000 字）")

    target = normalize_element_target(target_element)
    meta = _load_meta(package_dir)
    outline = _slide_outline(meta)
    page_count = len(outline)

    plan_issue = issue
    target_block = format_target_for_prompt(target)
    if target_block:
        plan_issue = f"{issue}\n\n{target_block}"

    plan = plan_editor_actions(
        plan_issue,
        page_count=page_count,
        current_file=slide_file,
        page_index=page_index,
        slide_outline=outline,
        mock=mock,
    )
    actions = list(plan.get("actions") or [])
    plan_summary = str(plan.get("summary") or "").strip()
    # If user pinned an image element, ensure regenerate_image targets that file.
    pinned_image = image_filename_from_target(target)
    if pinned_image:
        for action in actions:
            if action.get("op") == OP_REGENERATE_IMAGE and not action.get("imageFile"):
                action["imageFile"] = pinned_image
    _log(
        log,
        f"[editor-assist] plan source={plan.get('source')} "
        f"actions={len(actions)} summary={plan_summary}"
        + (f" target={target.get('dataSlot') or target.get('editorId') or target.get('tagName')}" if target else ""),
    )

    results: list[dict[str, Any]] = []
    changed_files: list[str] = []
    deleted_files: list[str] = []
    regenerated_images: list[str] = []
    activate_file: str | None = None
    result_file: str | None = None
    result_title: str | None = None
    insert_at: int | None = None
    primary_intent = "rewrite"

    for idx, action in enumerate(actions):
        op = str(action.get("op") or "")
        _log(log, f"[editor-assist] ({idx + 1}/{len(actions)}) op={op}")
        try:
            if op == OP_MODIFY:
                primary_intent = "rewrite"
                row = run_page_rewrite(
                    package_dir,
                    slide_file=action.get("file") or slide_file,
                    page_index=(
                        action.get("pageIndex")
                        if action.get("pageIndex") is not None
                        else page_index
                    ),
                    issue=str(action.get("instruction") or issue),
                    mock=mock,
                    target_element=target,
                    log=log,
                )
                row = {**row, "op": OP_MODIFY}
                result_file = str(row.get("file") or "") or result_file
                result_title = str(row.get("title") or "") or result_title
                if row.get("file"):
                    changed_files.append(str(row["file"]))
                activate_file = result_file or activate_file
            elif op == OP_REGENERATE_IMAGE:
                if primary_intent == "rewrite":
                    pass
                else:
                    primary_intent = "rewrite"
                row = run_page_image_regen(
                    package_dir,
                    prompt=str(action.get("prompt") or issue),
                    slide_file=action.get("file") or slide_file,
                    page_index=(
                        action.get("pageIndex")
                        if action.get("pageIndex") is not None
                        else page_index
                    ),
                    image_file=action.get("imageFile") or pinned_image,
                    mock=mock,
                    log=log,
                )
                result_file = str(row.get("file") or "") or result_file
                if row.get("file"):
                    changed_files.append(str(row["file"]))
                for name in row.get("regeneratedImages") or []:
                    regenerated_images.append(str(name))
                activate_file = result_file or activate_file
            elif op == OP_ADD:
                primary_intent = "generate"
                row = run_page_generate(
                    package_dir,
                    issue=str(action.get("instruction") or issue),
                    after_file=action.get("file") or slide_file,
                    after_page_index=(
                        action.get("afterPageIndex")
                        if action.get("afterPageIndex") is not None
                        else page_index
                    ),
                    title_hint=action.get("title") or action.get("titleHint"),
                    mock=mock,
                    log=log,
                )
                row = {**row, "op": OP_ADD}
                result_file = str(row.get("file") or "") or result_file
                result_title = str(row.get("title") or "") or result_title
                if row.get("insertAt") is not None:
                    insert_at = int(row["insertAt"])
                if row.get("file"):
                    changed_files.append(str(row["file"]))
                activate_file = result_file or activate_file
            elif op == OP_DELETE:
                primary_intent = "delete"
                row = run_page_delete(
                    package_dir,
                    slide_file=action.get("file") or slide_file,
                    page_index=(
                        action.get("pageIndex")
                        if action.get("pageIndex") is not None
                        else page_index
                    ),
                    log=log,
                )
                row = {**row, "op": OP_DELETE}
                result_file = str(row.get("file") or "") or result_file
                for name in row.get("deletedFiles") or [row.get("file")]:
                    if name:
                        deleted_files.append(str(name))
                activate_file = str(row.get("activateFile") or "") or activate_file
            else:
                raise RuntimeError(f"未知动作：{op}")
            results.append(row)
        except Exception as exc:  # noqa: BLE001
            _log(log, f"[editor-assist] FAIL op={op} — {exc}")
            results.append({"ok": False, "op": op, "error": str(exc)})
            # Stop on hard failures for delete/add; continue after image/modify soft fail? 
            # Prefer stop to avoid cascading inconsistency.
            break

    ok = bool(results) and all(r.get("ok", True) for r in results)
    if not results:
        raise RuntimeError("没有可执行的动作")

    # de-dupe preserve order
    def _uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in items:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    summary_md = _build_summary_markdown(
        plan_summary=plan_summary, issue=issue, results=results
    )
    template_id = str(
        meta.get("public_id") or meta.get("template_id") or package_dir.name
    )
    # refresh meta id after mutations
    try:
        meta2 = json.loads((package_dir / "template.json").read_text(encoding="utf-8"))
        template_id = str(
            meta2.get("public_id") or meta2.get("template_id") or template_id
        )
    except Exception:
        pass

    return {
        "ok": ok,
        "template_id": template_id,
        "pipeline": "editor-assist",
        "intent": primary_intent,
        "summary": plan_summary,
        "summaryMarkdown": summary_md,
        "planSource": plan.get("source"),
        "actions": actions,
        "results": results,
        "file": result_file,
        "title": result_title,
        "insertAt": insert_at,
        "activateFile": activate_file,
        "changedFiles": _uniq(changed_files),
        "deletedFiles": _uniq(deleted_files),
        "regeneratedImages": _uniq(regenerated_images),
        "targetElement": target,
        "error": None
        if ok
        else next(
            (str(r.get("error")) for r in results if not r.get("ok", True)),
            "部分动作失败",
        ),
    }
