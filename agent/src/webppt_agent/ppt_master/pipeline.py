"""PPT Master 生成管线：LLM 规划/写 SVG → 质检 → svg_to_pptx → html-slide 包。"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from webppt_agent.config import is_mock, llm_config, llm_light_config, load_env
from webppt_agent.llm import chat_json, chat_text, make_client_pool
from webppt_agent.ppt_master import prompts
from webppt_agent.ppt_master.paths import (
    assert_ppt_master_ready,
    ppt_master_python,
    ppt_master_root,
    repo_root,
    skill_dir,
)
from webppt_agent.ppt_master.sanitize import (
    apply_overflow_fixes_from_report,
    is_well_formed_svg,
    sanitize_svg_dir,
    sanitize_svg_text,
    salvage_truncated_svg,
    generation_compatibility_issues,
)
from webppt_agent.ppt_master.styles import force_plan_style, style_title_ban_tokens
from webppt_agent.usage import current_usage, track_usage, use_usage

try:
    import xml.etree.ElementTree as ET
except ImportError:  # pragma: no cover
    ET = None  # type: ignore

LogFn = Callable[[str], None]


def _log(fn: LogFn | None, msg: str) -> None:
    line = msg if msg.endswith("\n") else msg + "\n"
    if fn:
        fn(line)
    else:
        sys.stdout.write(line)
        sys.stdout.flush()


def _slug(text: str, fallback: str = "演示模板") -> str:
    """Filesystem-safe pack name; prefer Chinese, keep letters/digits."""
    s = (text or "").strip()
    # Windows-illegal + control chars
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\u4e00-\u9fff.\-（）()·—]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s).strip(".-")
    # Avoid pure-English kebab when we can fall back
    if not s:
        s = fallback
    # Allow ~15 CJK chars + light punctuation (was 40; keep headroom)
    return s[:48]


def _cjk_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _prompt_allows_style_token(prompt: str, token: str) -> bool:
    """True if the user prompt itself treats the token as content (not just style=)."""
    p = prompt or ""
    if not token or token not in p:
        return False
    # Ignore "风格=舞台灯光" / "风格：代码编辑器" side-mentions
    stripped = re.sub(
        rf"风格\s*[=：:]\s*[^\n；;]*{re.escape(token)}[^\n；;]*",
        "",
        p,
    )
    return token in stripped


def _topic_hint_from_prompt(prompt: str) -> str:
    """First-line content topic; strip style=… clauses."""
    line = (prompt or "").split("\n")[0].strip()
    line = re.sub(r"风格\s*[=：:][^\n；;]*", "", line)
    line = re.sub(r"[；;]\s*禁止[^；;]*", "", line)
    line = re.sub(r"\s+", "", line)
    return line[:48]


def _scrub_style_from_pack_name(
    name: str,
    *,
    visual_style: str,
    prompt: str,
) -> str:
    """Remove style-metaphor fragments from pack titles unless prompt owns them."""
    out = (name or "").strip()
    if not out:
        return out
    for token in style_title_ban_tokens(visual_style):
        if len(token) < 2:
            continue
        if token not in out:
            continue
        if _prompt_allows_style_token(prompt, token):
            continue
        out = out.replace(token, "")
        out = re.sub(r"风(?=发布|手册|册|会|案)", "", out)
    out = re.sub(r"[-—_·\s]{2,}", "", out).strip("-—_· ")
    return out


def _resolve_pack_name(
    *,
    label_zh: Any,
    template_id: Any,
    prompt: str,
    out_root: Path,
    visual_style: str = "",
) -> str:
    """User-facing folder / pptx stem: content topic, not visual-style metaphor."""
    label = str(label_zh or "").strip()
    tid = str(template_id or "").strip()
    prompt_line = _topic_hint_from_prompt(prompt)

    if label and _has_cjk(label):
        base = label
    elif tid and _has_cjk(tid):
        base = tid
    elif prompt_line and _has_cjk(prompt_line):
        base = prompt_line
    elif label:
        base = label
    elif tid:
        base = tid
    else:
        base = "演示模板"

    base = _scrub_style_from_pack_name(
        base, visual_style=visual_style or "", prompt=prompt or ""
    )
    if (
        _cjk_len(base) < 6
        and prompt_line
        and _has_cjk(prompt_line)
        and not re.search(r"(发布会|手册|册|提案|首演|开幕)", base)
    ):
        base = _scrub_style_from_pack_name(
            prompt_line, visual_style=visual_style or "", prompt=prompt or ""
        ) or base

    name = _slug(base, "演示模板")
    if not _has_cjk(name):
        # Force a Chinese fallback prefix when model still emitted English-only id
        name = _slug(f"模板-{name}", "演示模板")
    # Soft expand ultra-short names using prompt topic when possible
    if (
        _cjk_len(name) < 6
        and prompt_line
        and _has_cjk(prompt_line)
        and not re.search(r"(发布会|手册|册|提案|首演|开幕)", name)
    ):
        merged = _slug(f"{name}-{prompt_line}", name)
        merged = _scrub_style_from_pack_name(
            merged, visual_style=visual_style or "", prompt=prompt or ""
        )
        merged = _slug(merged, name)
        if _cjk_len(merged) >= _cjk_len(name):
            name = merged[:48]

    candidate = name
    if not (out_root / candidate).exists() and not (repo_root() / "drafts" / f"{candidate}.pptx").exists():
        return candidate
    for i in range(2, 100):
        cand = f"{name}-{i}"
        if not (out_root / cand).exists() and not (repo_root() / "drafts" / f"{cand}.pptx").exists():
            return cand
    return f"{name}-{secrets.token_hex(2)}"


def _strip_svg(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:xml|svg)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("<svg")
    if start < 0:
        start = text.find("<?xml")
    if start >= 0:
        text = text[start:]
    end = text.rfind("</svg>")
    if end >= 0:
        text = text[: end + len("</svg>")]
    if not text.lstrip().startswith("<?xml"):
        text = '<?xml version="1.0" encoding="UTF-8"?>\n' + text.lstrip()
    return text.strip() + "\n"


def _run(cmd: list[str], *, cwd: Path | None = None, log: LogFn | None = None) -> None:
    _log(log, f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.stdout:
        _log(log, proc.stdout.rstrip())
    if proc.stderr:
        _log(log, proc.stderr.rstrip())
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def _quality_report(project: Path, log: LogFn | None = None) -> tuple[bool, dict[str, Any]]:
    skill = skill_dir()
    py = str(ppt_master_python())
    cmd = [py, str(skill / "scripts" / "svg_quality_checker.py"), str(project), "--quick-generate", "--stage", "final", "--json"]
    _log(log, f"$ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ppt_master_root()), capture_output=True, text=True)
    if proc.stdout:
        _log(log, proc.stdout.rstrip())
    if proc.stderr:
        _log(log, proc.stderr.rstrip())
    report_path = project / "validation" / "svg_quality_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"质量检查未生成有效报告：{exc}") from exc
    return proc.returncode == 0, report


def _page_quality_report(
    project: Path,
    file_name: str,
    log: LogFn | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Run the same gate on one freshly authored page."""
    skill = skill_dir()
    py = str(ppt_master_python())
    cmd = [
        py,
        str(skill / "scripts" / "svg_quality_checker.py"),
        str(project),
        "--quick-generate",
        "--stage",
        "page",
        "--page",
        file_name,
        "--json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ppt_master_root()),
        capture_output=True,
        text=True,
    )
    report_path = project / "validation" / "svg_quality_page_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"单页质量检查未生成有效报告：{exc}") from exc
    if proc.returncode != 0 and proc.stderr:
        _log(log, proc.stderr.rstrip())
    return proc.returncode == 0, report


def _report_page_errors(report: dict[str, Any], file_name: str) -> list[str]:
    """Return concise page-local blocking diagnostics from a checker report."""
    for item in report.get("files", []) if isinstance(report, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file") or Path(str(item.get("path") or "")).name)
        if name != file_name:
            continue
        return [
            error if isinstance(error, str) else str(error.get("message") or error)
            for error in (item.get("errors") or [])
        ]
    return []


def _preflight_generated_page(
    project: Path,
    file_name: str,
    slide: dict[str, Any],
    log: LogFn | None,
    *,
    enable_repair: bool,
) -> bool:
    """Check and repair one page before the rest of the deck is accepted."""
    passed, report = _page_quality_report(project, file_name, log)
    if passed:
        _log(log, f"[svg] page preflight passed {file_name}")
        return True

    report_path = project / "validation" / "svg_quality_page_report.json"
    touched = apply_overflow_fixes_from_report(project, report_path=report_path)
    if touched:
        _log(log, f"[svg] page deterministic layout repair {file_name}")
        passed, report = _page_quality_report(project, file_name, log)
        if passed:
            return True

    errors = _report_page_errors(report, file_name)
    path = project / "svg_output" / file_name
    layout_errors = [
        message
        for message in errors
        if any(
            marker in message
            for marker in (
                "[TEXT_TEXT_OVERLAP]",
                "[TEXT_SHAPE_OCCLUSION]",
                "[TEXT_CANVAS_CLIPPING]",
                "[SHAPE_CANVAS_CLIPPING]",
                "data-pptx-bounds",
            )
        )
    ]
    if enable_repair and layout_errors and path.is_file():
        cfg = llm_config()
        pool = make_client_pool(cfg)
        repaired = chat_text(
            pool=pool,
            model=cfg.model,
            system=prompts.SYSTEM_SVG_REPAIR,
            user=prompts.user_svg_repair(
                original_svg=path.read_text(encoding="utf-8"),
                slide=slide,
                issues=layout_errors[:12],
            ),
            temperature=0.2,
        )
        candidate = sanitize_svg_text(_strip_svg(repaired))
        if is_well_formed_svg(candidate):
            path.write_text(candidate, encoding="utf-8")
            passed, report = _page_quality_report(project, file_name, log)
            if passed:
                _log(log, f"[svg] page repaired and passed {file_name}")
                return True

    remaining = _report_page_errors(report, file_name)
    detail = remaining[0] if remaining else "unknown blocking issue"
    _log(log, f"[svg] page preflight deferred to final repair {file_name}: {detail}")
    return False


def _repair_failed_svgs(
    project: Path,
    slides: list[dict[str, Any]],
    plan_json: str,
    log: LogFn | None,
    rounds: int = 2,
) -> bool:
    """Run up to ``rounds`` QA + repair cycles.

    Returns True if the final gate passes. Returns False (soft-pass) when
    blocking errors remain after the repair budget — caller should still export.
    """
    del plan_json  # reserved for richer repair context
    cfg = llm_config()
    pool = make_client_pool(cfg)
    by_file = {str(s.get("file")): s for s in slides}
    previous_signature: tuple[int, tuple[str, ...]] | None = None
    for attempt in range(1, rounds + 1):
        passed, report = _quality_report(project, log)
        if passed:
            _log(log, f"[quality] passed after repair round {attempt - 1}")
            return True
        blocking = report.get("categories", {}).get("blocking", {}) if isinstance(report, dict) else {}
        blocking_count = int(blocking.get("count", 0) or 0) if isinstance(blocking, dict) else 0
        blocking_files = tuple(
            sorted(
                str(item.get("file") or Path(str(item.get("path") or "")).name)
                for item in (report.get("files", []) if isinstance(report, dict) else [])
                if isinstance(item, dict) and item.get("errors")
            )
        )
        signature = (blocking_count, blocking_files)
        if previous_signature == signature:
            _log(
                log,
                f"[quality] soft-pass: round {attempt} repeated the same blocking "
                f"errors ({blocking_count}); continue to export",
            )
            return False
        previous_signature = signature

        # First handle mechanical bounds errors deterministically. This is
        # safer than asking an LLM to rewrite a page when only a container is
        # a few pixels too small.
        touched = apply_overflow_fixes_from_report(project)
        if touched:
            _log(log, f"[quality] deterministic bounds repair: {touched} page(s)")
            passed, report = _quality_report(project, log)
            if passed:
                _log(log, "[quality] passed after deterministic repair")
                return True
        grouped: dict[str, list[str]] = {}
        for item in report.get("files", []) if isinstance(report, dict) else []:
            if not isinstance(item, dict):
                continue
            errors = item.get("errors") or []
            messages = [e if isinstance(e, str) else str(e.get("message") or e) for e in errors]
            if messages:
                grouped[str(item.get("file") or Path(str(item.get("path") or "")).name)] = messages
        if not grouped:
            _log(log, "[quality] soft-pass: gate failed but no page-level errors to repair")
            return False
        _log(log, f"[quality] repair round {attempt}/{rounds}: {len(grouped)} page(s)")
        for file_name, issues in grouped.items():
            slide = by_file.get(file_name)
            path = project / "svg_output" / file_name
            if not slide or not path.is_file():
                continue
            raw = path.read_text(encoding="utf-8")
            # Deterministic CSS strip / truncate salvage first — avoids LLM
            # rewriting multi-thousand-rect pixel pages into truncated XML.
            cleaned = sanitize_svg_text(raw)
            if cleaned != raw and is_well_formed_svg(cleaned):
                path.write_text(cleaned, encoding="utf-8")
                raw = cleaned
            only_css = issues and all(
                any(
                    key in msg.lower()
                    for key in ("<style>", "class attribute", "@font-face", "@import", "css")
                )
                for msg in issues
            )
            if only_css and is_well_formed_svg(raw):
                continue
            if any("Invalid XML" in msg or "well-formed" in msg for msg in issues):
                salvaged = salvage_truncated_svg(raw)
                if salvaged and is_well_formed_svg(salvaged):
                    path.write_text(sanitize_svg_text(salvaged), encoding="utf-8")
                continue
            repaired = chat_text(
                pool=pool,
                model=cfg.model,
                system=prompts.SYSTEM_SVG_REPAIR,
                user=prompts.user_svg_repair(original_svg=raw, slide=slide, issues=issues),
                temperature=0.2,
            )
            candidate = sanitize_svg_text(_strip_svg(repaired))
            if is_well_formed_svg(candidate):
                path.write_text(candidate, encoding="utf-8")
            else:
                _log(log, f"[quality] discard broken LLM repair for {file_name}; keep prior SVG")
    passed, _ = _quality_report(project, log)
    if passed:
        return True
    _log(
        log,
        f"[quality] soft-pass: still blocking after {rounds} repair round(s); continue to export",
    )
    return False


def _mock_plan(prompt: str, pages: int, visual_style: str) -> dict[str, Any]:
    tid = _slug(prompt.split("\n")[0][:24], "演示模板")
    if not _has_cjk(tid):
        tid = "演示模板"
    roles = ["cover", "section", "content", "content", "content", "ending"]
    while len(roles) < pages:
        roles.insert(-1, "content")
    roles = roles[:pages]
    slides = []
    for i, role in enumerate(roles, 1):
        slides.append(
            {
                "file": f"{i:02d}_{role}.svg",
                "role": role if role != "content" else "content",
                "title": f"示意页 {i}",
                "core_message": f"Mock：{prompt[:40] or '演示'}",
                "geometry": "dark panel + accent bar",
                "layout_regions": [
                    {
                        "id": "title",
                        "role": "page-title",
                        "bounds": [72, 230, 1000, 80],
                        "padding": [12, 12, 12, 12],
                        "clearance": 16,
                    },
                    {
                        "id": "body",
                        "role": "body",
                        "bounds": [72, 340, 1000, 80],
                        "padding": [12, 12, 12, 12],
                        "clearance": 16,
                    },
                ],
                "visual_hook": "accent bar",
                "density": "anchor",
                "motif_use": "固定",
            }
        )
    return {
        "template_id": tid,
        "label_zh": tid,
        "product": "NovaForge",
        "visual_style": visual_style or "dark-tech",
        "mode": "showcase",
        "palette": {
            "bg": "#05070F",
            "panel": "#0E1424",
            "text": "#F4F7FF",
            "muted": "#8B93A7",
            "accent": "#3DDCFF",
            "accent2": "#7C5CFF",
        },
        "slides": slides,
    }


def _mock_svg(slide: dict[str, Any], palette: dict[str, str]) -> str:
    bg = palette.get("bg", "#05070F")
    text = palette.get("text", "#F4F7FF")
    muted = palette.get("muted", "#8B93A7")
    accent = palette.get("accent", "#3DDCFF")
    role = slide.get("role") or "content"
    title = slide.get("title") or "Title"
    msg = slide.get("core_message") or ""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"
  data-pptx-page-role="{role}"
  font-family="Arial, Microsoft YaHei, sans-serif">
  <rect id="bg" x="0" y="0" width="1280" height="720" fill="{bg}" data-pptx-role="background"/>
  <rect id="bar" x="72" y="200" width="72" height="6" fill="{accent}" data-pptx-role="decoration"/>
  <g id="title" data-pptx-bounds="72 230 1000 80" data-slot="title" data-slot-type="text" data-slot-role="page-title">
    <text x="72" y="290" fill="{text}" font-size="40" font-weight="700" data-slot="title" data-slot-type="text" data-slot-role="page-title">{title}</text>
  </g>
  <g id="body" data-pptx-bounds="72 340 1000 80" data-slot="body" data-slot-type="text" data-slot-role="body">
    <text x="72" y="380" fill="{muted}" font-size="20" data-slot="body" data-slot-type="text" data-slot-role="body">{msg}</text>
  </g>
</svg>
'''


ROLE_ALIASES = {
    "hero": "cover",
    "title": "cover",
    "titlepage": "cover",
    "agenda": "toc",
    "contents": "toc",
    "outline": "toc",
    "chapter": "section",
    "divider": "section",
    "break": "section",
    "data": "content",
    "metrics": "content",
    "metric": "content",
    "kpi": "content",
    "body": "content",
    "feature": "content",
    "features": "content",
    "capability": "content",
    "capabilities": "content",
    "closing": "ending",
    "close": "ending",
    "end": "ending",
    "finale": "ending",
    "outro": "ending",
    "thankyou": "ending",
    "thanks": "ending",
}


def _normalize_slide_role(role: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(role or "content").strip().lower())
    if key in {"cover", "toc", "section", "content", "ending"}:
        return key
    return ROLE_ALIASES.get(key, str(role or "content").strip().lower())


def _validate_plan(plan: dict[str, Any], requested_pages: int) -> None:
    """Fail early on roster errors that otherwise surface as bad decks."""
    slides = plan.get("slides")
    if not isinstance(slides, list) or not slides:
        raise RuntimeError("规划结果缺少 slides")
    if len(slides) != requested_pages:
        raise RuntimeError(f"规划页数不匹配：要求 {requested_pages}，实际 {len(slides)}")
    seen: set[str] = set()
    allowed = {"cover", "toc", "section", "content", "ending"}
    for i, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            raise RuntimeError(f"第 {i} 页规划不是对象")
        name = str(slide.get("file") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.svg", name):
            raise RuntimeError(f"第 {i} 页文件名非法：{name!r}")
        if name in seen:
            raise RuntimeError(f"页面文件名重复：{name}")
        seen.add(name)
        role = _normalize_slide_role(slide.get("role"))
        slide["role"] = role
        if role not in allowed:
            raise RuntimeError(f"第 {i} 页 role 非法：{role}")
        if not str(slide.get("title") or "").strip():
            raise RuntimeError(f"第 {i} 页缺少 title")
        if not str(slide.get("core_message") or "").strip():
            raise RuntimeError(f"第 {i} 页缺少 core_message")
        regions = slide.get("layout_regions")
        if not isinstance(regions, list) or not regions:
            raise RuntimeError(f"第 {i} 页缺少 layout_regions")
        region_ids: set[str] = set()
        region_boxes: list[tuple[str, float, float, float, float, float]] = []
        for region in regions:
            if not isinstance(region, dict):
                raise RuntimeError(f"第 {i} 页 layout_regions 含非对象")
            region_id = str(region.get("id") or "").strip()
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", region_id):
                raise RuntimeError(f"第 {i} 页 layout region id 非法：{region_id!r}")
            if region_id in region_ids:
                raise RuntimeError(f"第 {i} 页 layout region id 重复：{region_id}")
            region_ids.add(region_id)
            bounds = region.get("bounds")
            padding = region.get("padding")
            try:
                x, y, width, height = [float(value) for value in bounds]
                pad_top, pad_right, pad_bottom, pad_left = [
                    float(value) for value in padding
                ]
                clearance = float(region.get("clearance"))
            except (TypeError, ValueError):
                raise RuntimeError(
                    f"第 {i} 页 layout region {region_id} 的 bounds/padding/clearance 非法"
                )
            if len(bounds) != 4 or len(padding) != 4:
                raise RuntimeError(
                    f"第 {i} 页 layout region {region_id} 必须使用四值 bounds/padding"
                )
            if (
                width <= 0
                or height <= 0
                or min(pad_top, pad_right, pad_bottom, pad_left, clearance) < 0
                or pad_left + pad_right >= width
                or pad_top + pad_bottom >= height
            ):
                raise RuntimeError(f"第 {i} 页 layout region {region_id} 无有效文字内框")
            if x < 40 or y < 40 or x + width > 1240 or y + height > 680:
                raise RuntimeError(f"第 {i} 页 layout region {region_id} 超出 40px 安全区")
            region_boxes.append((region_id, x, y, x + width, y + height, clearance))
        for region_index, first in enumerate(region_boxes):
            for second in region_boxes[region_index + 1 :]:
                separation = max(first[5], second[5])
                if not (
                    first[3] + separation <= second[1]
                    or second[3] + separation <= first[1]
                    or first[4] + separation <= second[2]
                    or second[4] + separation <= first[2]
                ):
                    raise RuntimeError(
                        f"第 {i} 页 layout regions {first[0]}/{second[0]} 未保留 clearance"
                    )


CREATIVE_SEEDS = (
    "Signal / radar：用轨道、扫描线和信号强弱表达从问题到结果的推进",
    "Terrain / journey：用地形、路径、坐标和层级表达从现状到行动的路线",
    "Editorial / artifact：用杂志章节、批注、索引和材质切片建立高级编辑感",
    "System / constellation：用节点、连接、环形关系和局部放大表达复杂系统",
)

CREATIVE_SEEDS_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "ink-notes": (
        "Manifesto ink：中心主张被手绘圆圈圈住，箭头分支出证据与反例",
        "Strike-through rewrite：旧说法被划掉，旁边写入新定义",
        "Bracketed proof：一条大括号把三条证据收进同一主张",
    ),
    "sketch-notes": (
        "Whiteboard map：手绘框与连线搭出一张可讲解的思维图",
        "Margin doodles：主论点很大，边缘只有少量强调短划",
        "Before/after sketch：左右手绘对照，中间一条替换箭头",
    ),
    "ink-wash": (
        "留白呼吸：大面积空白托住一行主张，墨色只作点睛",
        "单峰构图：一块深墨色块压在一侧，文字在留白区",
        "层叠淡墨：两到三道半透明色带暗示层次，不堆装饰",
    ),
    "chalkboard": (
        "粉笔提纲：深色板面 + 粉笔字阶 + 一条强调下划线",
        "课堂推导：步骤编号横向展开，像板书推演",
        "粉笔圈点：关键数字被粉笔圈出，周围留出板面空白",
    ),
    "swiss-minimal": (
        "Grid strike：严格网格 + 一条高对比色条切开信息",
        "Aggressive whitespace：半页留白，标题压到边缘",
        "Typographic ladder：字号阶梯决定层级，几乎零装饰",
    ),
    "editorial": (
        "Magazine spread：大标题压图区 + 批注式旁注",
        "Pull-quote：一句引言占半屏，页码/栏目索引很小",
        "Column break：非对称栏宽与水平分割线",
    ),
    "brutalist": (
        "Raw block：超大粗体压满，硬边色块碰撞",
        "System dump：像未排完的印刷稿，信息直接堆出冲击",
        "High-contrast stamp：印章式标签切开页面",
    ),
    "gallery-white": (
        "Exhibit plane：半页到满幅色块当展品，墙签式短注",
        "Caption margin：大留白 + 边缘小字，像美术馆说明牌",
        "Folio architecture：超大页码作结构，内容极少",
    ),
    "midnight-luxe": (
        "Night void：大面积暗场托住一行短标题",
        "Jewelry rule：一条细强调线，不要霓虹光晕",
        "Stage band：底部静音色带承托收束句",
    ),
    "nordic-calm": (
        "Horizon band：淡色水平分区，像平静地平线",
        "Soft anchor：一个柔和圆形托住短主张",
        "Uneven two-column：不等宽双栏，气口充足",
    ),
    "kinetic-poster": (
        "Diagonal slash：斜切分区，标题压过切割线",
        "Mega word：一个词占半屏，其余全是短注",
        "Ground band：底部色带托一句行动语",
    ),
    "dossier-archive": (
        "Index rail：左侧 01/02/03 索引轨 + 右侧正文井",
        "File header：顶栏文件名与档案号",
        "Ruled note：细线框批注，像简报附注而非贴纸",
    ),
}


def _creative_seeds_for(style: str) -> tuple[str, ...]:
    sid = (style or "").strip()
    if sid in CREATIVE_SEEDS_BY_FAMILY:
        return CREATIVE_SEEDS_BY_FAMILY[sid]
    if sid in {"paper-cut", "zine", "vintage-poster", "memphis", "pixel-art"}:
        return CREATIVE_SEEDS_BY_FAMILY.get("editorial", CREATIVE_SEEDS)[:3]
    if sid in {"dark-tech", "blueprint", "glassmorphism"}:
        return CREATIVE_SEEDS[:3]
    return (
        CREATIVE_SEEDS[2],
        CREATIVE_SEEDS[1],
        CREATIVE_SEEDS_BY_FAMILY["swiss-minimal"][0],
    )


def _plan_critique(
    plan: dict[str, Any],
    *,
    prompt: str = "",
    visual_style: str = "",
) -> list[str]:
    slides = plan.get("slides") or []
    geometries = [str(s.get("geometry") or "").strip().lower() for s in slides if isinstance(s, dict)]
    issues: list[str] = []
    repeats = {g for g in geometries if g and geometries.count(g) > 1}
    if repeats:
        issues.append(f"重复构图：{', '.join(sorted(repeats))}")
    if len(set(geometries)) < max(3, min(4, len(geometries))):
        issues.append("构图类型过少，需要至少 3 种明显不同的空间骨架")
    joined = " ".join(geometries)
    if any(token in joined for token in ("三栏", "three cards", "3 cards", "three-column")):
        issues.append("出现套路化三栏卡片，请改为非对称、路径、关系图或大数字构图")
    hooks = [str(s.get("visual_hook") or "").strip() for s in slides if isinstance(s, dict)]
    if hooks and sum(bool(h) for h in hooks) < max(1, len(hooks) // 2):
        issues.append("多数页面缺少 visual_hook")

    # Pack title must be content topic, not visual-style metaphor
    title = str(plan.get("label_zh") or plan.get("template_id") or "").strip()
    style = visual_style or str(plan.get("visual_style") or "")
    bad_tokens = [
        t
        for t in style_title_ban_tokens(style)
        if t and t in title and not _prompt_allows_style_token(prompt, t)
    ]
    if bad_tokens:
        issues.append(
            "template_id/label_zh 把视觉风格隐喻写进了书名"
            f"（含：{'、'.join(bad_tokens[:3])}）。"
            "请改成内容主题（产品/活动/议题），例如「星河智能产品发布会」或「春日话剧首演手册」；"
            "同一风格可服务完全不同主题，禁止「舞台灯光AI发布会」「代码编辑器风手册」这类命名"
        )
    return issues


def _creative_score(
    plan: dict[str, Any],
    *,
    prompt: str = "",
    visual_style: str = "",
) -> float:
    slides = plan.get("slides") or []
    if not slides:
        return 0.0
    geometries = [str(s.get("geometry") or "").strip().lower() for s in slides if isinstance(s, dict)]
    hooks = [str(s.get("visual_hook") or "").strip() for s in slides if isinstance(s, dict)]
    variety = min(1.0, len(set(g for g in geometries if g)) / max(4, len(slides) * 0.6))
    hooks_ratio = sum(bool(h) for h in hooks) / max(1, len(slides))
    role_bonus = 0.2 if any(isinstance(s, dict) and s.get("role") == "section" for s in slides) else 0.0
    penalty = (
        0.25
        if _plan_critique(plan, prompt=prompt, visual_style=visual_style)
        else 0.0
    )
    return round(max(0.0, min(1.0, 0.55 * variety + 0.25 * hooks_ratio + role_bonus - penalty)), 3)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _want_images(*, skip_images: bool | None) -> bool:
    if skip_images is True:
        return False
    if skip_images is False:
        return True
    return not _truthy_env("AGENT_SKIP_IMAGE")


def _safe_image_filename(stem: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", stem).strip("-").lower() or "slide"
    name = f"{base}.png"
    if name not in used:
        used.add(name)
        return name
    for i in range(2, 100):
        cand = f"{base}-{i}.png"
        if cand not in used:
            used.add(cand)
            return cand
    used.add(name)
    return name


def _assign_plan_images(
    slides: list[dict[str, Any]],
    *,
    enable: bool,
) -> dict[str, dict[str, str]]:
    """Mutate slides with image_file + image_aspect; return filename -> {prompt,size}."""
    from webppt_agent.image.generate import infer_image_aspect

    refs: dict[str, dict[str, str]] = {}
    if not enable:
        for slide in slides:
            if isinstance(slide, dict):
                slide["need_image"] = False
                slide.pop("image_file", None)
                slide.pop("image_aspect", None)
        return refs
    used: set[str] = set()
    for i, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            continue
        role = str(slide.get("role") or "content")
        raw_need = slide.get("need_image")
        if raw_need is None:
            need = role in {"cover", "section"}
        else:
            need = bool(raw_need) and str(raw_need).strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
        if not need:
            slide["need_image"] = False
            slide.pop("image_file", None)
            slide.pop("image_aspect", None)
            continue
        stem = Path(str(slide.get("file") or f"{i:02d}_slide")).stem
        filename = _safe_image_filename(stem, used)
        hint = str(
            slide.get("image_hint")
            or slide.get("image_alt")
            or slide.get("visual_hook")
            or slide.get("title")
            or f"editorial illustration for slide {i}"
        ).strip()
        aspect = infer_image_aspect(slide)
        slide["need_image"] = True
        slide["image_file"] = filename
        slide["image_hint"] = hint
        slide["image_aspect"] = aspect
        if not str(slide.get("image_role") or "").strip():
            role = str(slide.get("role") or "content")
            slide["image_role"] = (
                "hero"
                if role in {"cover", "section", "ending"}
                else "panel"
            )
        refs[filename] = {
            "prompt": hint,
            "size": aspect,
            "image_role": slide.get("image_role"),
            "copy_safe_region": slide.get("image_copy_safe"),
            "focal_region": slide.get("image_focal"),
        }
    return refs


def _scrub_svg_image_refs(svg: str, *, allowed: set[str], images_dir: Path) -> str:
    """Drop <image> that is external or points at a missing/unlisted file."""
    if ET is None or "<image" not in svg.lower():
        return svg
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return svg

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower() if tag else ""

    removed = 0
    for parent in root.iter():
        doomed: list[Any] = []
        for child in list(parent):
            if local(child.tag) != "image":
                continue
            href = (
                child.attrib.get("href")
                or child.attrib.get("{http://www.w3.org/1999/xlink}href")
                or ""
            ).strip()
            name = Path(href).name if href else ""
            ok = (
                href.startswith("../images/")
                and name in allowed
                and (images_dir / name).is_file()
                and not href.lower().startswith(("http://", "https://", "data:"))
            )
            if not ok:
                doomed.append(child)
        for child in doomed:
            parent.remove(child)
            removed += 1
    if removed == 0:
        return svg
    decl = ""
    raw = svg.lstrip()
    if raw.startswith("<?xml"):
        end = raw.find("?>")
        if end >= 0:
            decl = raw[: end + 2] + "\n"
    body = ET.tostring(root, encoding="unicode")
    if not body.lstrip().startswith("<?xml"):
        body = decl + body
    return body


def _materialize_plan_images(
    project: Path,
    refs: dict[str, Any],
    *,
    style_hint: str,
    palette: dict[str, Any],
    log: LogFn | None,
) -> list[str]:
    if not refs:
        return []
    from webppt_agent.image.generate import image_api_config, materialize_images

    images_dir = project / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    cfg = image_api_config()
    _log(
        log,
        f"[images] materialize ×{len(refs)} "
        f"skip={cfg.skip} model={cfg.model or '-'} base={cfg.base_url or '-'}",
    )
    theme_colors = {
        k: str(v)
        for k, v in (palette or {}).items()
        if isinstance(v, str) and v.startswith("#")
    }
    warnings = materialize_images(
        images_dir,
        refs,
        style_hint=style_hint,
        bg_hex=theme_colors.get("bg"),
        theme_colors=theme_colors,
    )
    for w in warnings:
        _log(log, f"[images] {w}")
    fixed = _repair_mismatched_image_files(images_dir, log=log)
    if fixed:
        _log(log, f"[images] normalized format ×{fixed}")
    return warnings


def _repair_mismatched_image_files(images_dir: Path, *, log: LogFn | None = None) -> int:
    """Re-encode files whose magic ≠ extension (e.g. JPEG bytes under .png)."""
    from webppt_agent.image.generate import coerce_image_bytes_to_suffix, sniff_image_suffix

    if not images_dir.is_dir():
        return 0
    n = 0
    for path in sorted(images_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        sniffed = sniff_image_suffix(data)
        want = ".jpg" if path.suffix.lower() == ".jpeg" else path.suffix.lower()
        if not sniffed or sniffed == want:
            continue
        try:
            fixed = coerce_image_bytes_to_suffix(data, path.suffix.lower())
            path.write_bytes(fixed)
            n += 1
            _log(log, f"[images] re-encoded {path.name}: {sniffed} → {want}")
        except Exception as exc:
            _log(log, f"[images] re-encode failed {path.name}: {exc}")
    return n


def _build_plan(
    *,
    prompt: str,
    pages: int,
    visual_style: str,
    use_mock: bool,
    log: LogFn | None,
    enable_images: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if use_mock:
        plan = _mock_plan(prompt, pages, visual_style or "dark-tech")
        return plan, {
            "candidates": 1,
            "selected": 1,
            "score": _creative_score(plan, prompt=prompt, visual_style=visual_style),
            "critique": [],
        }
    heavy_cfg = llm_config()
    if not heavy_cfg.api_keys:
        raise RuntimeError("未配置 LLM_API_KEY，无法运行 ppt-master 管线（或加 --mock）")
    # Plan is structural/JSON work.  Reuse the configured light tier when
    # available; SVG authoring keeps the heavy tier below.  If the light tier
    # is not configured, llm_light_config() transparently falls back to heavy.
    cfg = llm_light_config()
    pool = make_client_pool(cfg)
    seeds = _creative_seeds_for(visual_style)
    usage = current_usage()

    def build_candidate(seed: str) -> tuple[str, dict[str, Any] | None, str | None]:
        # ContextVars do not cross ThreadPoolExecutor workers automatically.
        with use_usage(usage):
            try:
                candidate = chat_json(
                    pool=pool,
                    model=cfg.model,
                    system=prompts.SYSTEM_PLAN,
                    user=prompts.user_plan(
                        prompt=prompt,
                        page_count=pages,
                        visual_style=visual_style,
                        creative_seed=seed,
                        enable_images=enable_images,
                    ),
                    temperature=0.7,
                )
                _validate_plan(candidate, pages)
                return seed, force_plan_style(candidate, visual_style), None
            except RuntimeError as exc:
                return seed, None, str(exc)

    # Candidate plans are independent. Keep a small cap to reduce wall time
    # without creating an unbounded burst against the provider rate limit.
    try:
        candidate_workers = max(
            1,
            min(int(os.environ.get("AGENT_PLAN_CONCURRENCY", "4")), len(seeds), 4),
        )
    except ValueError:
        candidate_workers = min(4, len(seeds))
    ordered: dict[str, tuple[dict[str, Any] | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=candidate_workers) as ex:
        futures = [ex.submit(build_candidate, seed) for seed in seeds]
        for future in futures:
            seed, candidate, error = future.result()
            ordered[seed] = (candidate, error)

    candidates: list[dict[str, Any]] = []
    for seed in seeds:
        candidate, error = ordered.get(seed, (None, "未返回候选"))
        if candidate is not None:
            candidates.append(candidate)
        elif error:
            _log(log, f"[plan] candidate rejected ({seed}): {error}")
    if not candidates:
        raise RuntimeError("所有创意 Plan 候选均未通过基础校验")
    ranked = sorted(
        enumerate(candidates, 1),
        key=lambda row: _creative_score(
            row[1], prompt=prompt, visual_style=visual_style
        ),
        reverse=True,
    )
    selected_idx, plan = ranked[0]
    critique = _plan_critique(plan, prompt=prompt, visual_style=visual_style)
    # One targeted rewrite pass prevents a high-scoring but cliché plan from
    # reaching SVG authoring while keeping Plan latency bounded.
    # Naming is scrubbed deterministically below, so a naming-only critique
    # does not justify another full-plan rewrite (which repeats the largest
    # prompt in this stage).  Keep the rewrite for layout/creative issues.
    rewrite_critique = [
        item
        for item in critique
        if "template_id/label_zh" not in item
    ]
    if rewrite_critique:
        revised = chat_json(
            pool=pool,
            model=cfg.model,
            system=prompts.SYSTEM_PLAN,
            user=prompts.user_plan_rewrite(
                prompt=prompt,
                page_count=pages,
                visual_style=visual_style,
                plan=plan,
                critique="；".join(rewrite_critique),
                enable_images=enable_images,
            ),
            temperature=0.6,
        )
        try:
            _validate_plan(revised, pages)
            revised = force_plan_style(revised, visual_style)
            if _creative_score(
                revised, prompt=prompt, visual_style=visual_style
            ) >= _creative_score(plan, prompt=prompt, visual_style=visual_style):
                plan = revised
                critique = _plan_critique(
                    plan, prompt=prompt, visual_style=visual_style
                )
        except RuntimeError as exc:
            _log(log, f"[plan] rewrite rejected: {exc}")
    plan = force_plan_style(plan, visual_style)
    # Deterministic scrub even if rewrite kept a style-flavored title
    for key in ("label_zh", "template_id"):
        raw = str(plan.get(key) or "").strip()
        if not raw:
            continue
        scrubbed = _scrub_style_from_pack_name(
            raw, visual_style=visual_style or "", prompt=prompt or ""
        )
        if scrubbed and scrubbed != raw:
            plan[key] = scrubbed
            _log(log, f"[plan] scrubbed {key}: {raw!r} → {scrubbed!r}")
    return plan, {
        "candidates": len(candidates),
        "selected": selected_idx,
        "score": _creative_score(plan, prompt=prompt, visual_style=visual_style),
                    "critique": critique,
    }

def _init_project(name: str, log: LogFn | None) -> Path:
    skill = skill_dir()
    py = str(ppt_master_python())
    root = ppt_master_root()
    projects = root / "projects"
    projects.mkdir(parents=True, exist_ok=True)
    # project_manager only appends _YYYYMMDD; same-day re-runs collide unless the
    # base name is unique per job.
    base = re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-")[:28] or "webppt"
    uniq = datetime.now().strftime("%H%M%S") + secrets.token_hex(2)
    init_name = f"{base}-{uniq}"
    before = {p.name for p in projects.iterdir() if p.is_dir()} if projects.is_dir() else set()
    _run(
        [py, str(skill / "scripts" / "project_manager.py"), "init", init_name, "--quick-generate"],
        cwd=root,
        log=log,
    )
    after = {p.name for p in projects.iterdir() if p.is_dir()}
    created = sorted(after - before)
    if not created:
        # fallback: newest matching prefix
        cands = sorted(
            [p for p in projects.iterdir() if p.is_dir() and p.name.startswith(init_name)],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not cands:
            raise RuntimeError("project_manager init 未创建项目目录")
        return cands[0]
    return projects / created[-1]


def _normalize_quality_gate(value: str | None, *, fast_preview: bool = False) -> str:
    """soft (default) | strict | skip. --fast-preview forces skip."""
    if fast_preview:
        return "skip"
    raw = (value or "soft").strip().lower()
    if raw in {"soft", "strict", "skip"}:
        return raw
    if raw in {"soft-pass", "softpass", "continue"}:
        return "soft"
    if raw in {"fail", "hard", "block"}:
        return "strict"
    if raw in {"off", "none", "disabled"}:
        return "skip"
    return "soft"


def _export_pptx(
    project: Path,
    pptx_out: Path,
    slides: list[dict[str, Any]],
    plan_json: str,
    log: LogFn | None,
    *,
    enable_repair: bool = True,
    quality_gate: str = "soft",
    strip_unsupported: bool = True,
) -> bool:
    """Export PPTX. Returns whether the SVG quality gate fully passed."""
    skill = skill_dir()
    py = str(ppt_master_python())
    pptx_out.parent.mkdir(parents=True, exist_ok=True)
    svg_dir = project / "svg_output"
    gate_mode = _normalize_quality_gate(quality_gate)

    # Keep normalization separate from the quality gate: normalization may fix
    # harmless syntax issues, but must never be used as a substitute for QA.
    fixed = sanitize_svg_dir(svg_dir, strip_unsupported=strip_unsupported)
    _log(
        log,
        f"[sanitize] structural+ids on {fixed} svg file(s)"
        f" · strip_unsupported={'on' if strip_unsupported else 'off'}",
    )

    # Soft-pass export still requires parseable SVG; salvage truncations now.
    for path in sorted(svg_dir.glob("*.svg")):
        raw = path.read_text(encoding="utf-8")
        if is_well_formed_svg(raw):
            continue
        salvaged = salvage_truncated_svg(raw)
        if salvaged and is_well_formed_svg(salvaged):
            path.write_text(
                sanitize_svg_text(salvaged, strip_unsupported=strip_unsupported),
                encoding="utf-8",
            )
            _log(log, f"[sanitize] salvaged truncated {path.name}")
        else:
            _log(log, f"[sanitize] WARN unparseable {path.name}; export may still fail")

    if gate_mode == "skip":
        _log(log, "[quality] quality-gate=skip：跳过质检与修复，直接导出")
        gate_passed = False
        export_flags = ["--enable-dangerous-nonconforming-svg-export"]
    else:
        if enable_repair:
            gate_passed = _repair_failed_svgs(project, slides, plan_json, log)
        else:
            _log(log, "[quality] svg-repair=off：跳过 bounds/LLM 修复轮次")
            gate_passed, _ = _quality_report(project, log)
            if gate_passed:
                _log(log, "[quality] SVG final gate passed (no repair)")
            else:
                _log(log, "[quality] gate failed; export without repair")

        if gate_passed:
            if enable_repair:
                _log(log, "[quality] SVG final gate passed")
            export_flags = ["--quick-generate"]
        elif gate_mode == "strict":
            raise RuntimeError(
                "SVG quality gate failed (quality-gate=strict)。"
                "可改 soft/skip，或打开 svg-repair / strip-unsupported 后再试。"
            )
        else:
            _log(
                log,
                "[quality] soft-pass → export with --enable-dangerous-nonconforming-svg-export",
            )
            # --quick-generate requires a passing final report; soft-pass cannot use it.
            export_flags = ["--enable-dangerous-nonconforming-svg-export"]

    _run(
        [
            py,
            str(skill / "scripts" / "svg_to_pptx.py"),
            str(project),
            *export_flags,
            "--no-notes",
            "-o",
            str(pptx_out),
        ],
        cwd=ppt_master_root(),
        log=log,
    )
    return gate_passed


def _convert_to_html_slide(
    pptx: Path,
    *,
    template_id: str,
    out_root: Path,
    log: LogFn | None,
    pack_format: str = "ppt-master",
) -> Path:
    script = repo_root() / "agent" / "scripts" / "pptx-to-template-package.mjs"
    if not script.is_file():
        raise FileNotFoundError(f"缺少转换脚本：{script}")
    fmt = "ppt-master" if pack_format == "ppt-master" else "html-slide"
    _run(
        [
            "node",
            str(script),
            "--pptx",
            str(pptx),
            "--out-root",
            str(out_root),
            "--template-id",
            template_id,
            "--status",
            "pending",
            "--format",
            fmt,
        ],
        cwd=repo_root(),
        log=log,
    )
    out_dir = out_root / template_id
    if not (out_dir / "template.json").is_file():
        raise RuntimeError(f"转换后未找到 template.json：{out_dir}")
    return out_dir


def _write_usage_into_template(pack_dir: Path, usage: Any) -> None:
    """Merge GenerationUsage into template.json after convert."""
    meta_path = pack_dir / "template.json"
    if not meta_path.is_file():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(meta, dict):
        return
    existing = meta.get("usage") if isinstance(meta.get("usage"), dict) else None
    meta["usage"] = usage.merge_into(existing)
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _layout_from_svg_filename(name: str) -> str:
    stem = Path(name).stem
    parts = stem.split("_", 1)
    raw = parts[1] if len(parts) == 2 and parts[0].isdigit() else stem
    layout = re.sub(r"[^a-zA-Z0-9\-]+", "-", raw).strip("-").lower() or "content"
    return layout


def _rewrite_svg_image_hrefs_for_package(svg: str) -> str:
    """Point SVG raster refs at ../images/ so they resolve from slides/*.html."""

    def _fix(m: re.Match[str]) -> str:
        attr, quote, rel = m.group(1), m.group(2), m.group(3)
        cleaned = rel.strip()
        if (
            cleaned.startswith("#")
            or cleaned.startswith("data:")
            or cleaned.startswith("http://")
            or cleaned.startswith("https://")
            or cleaned.startswith("url(")
        ):
            return m.group(0)
        # Only rewrite likely local image paths
        lower = cleaned.lower()
        looks_image = bool(
            re.search(r"\.(png|jpe?g|gif|webp|svg)(?:\?|$)", lower)
            or lower.startswith("images/")
            or lower.startswith("./images/")
            or lower.startswith("../images/")
        )
        if not looks_image:
            return m.group(0)
        cleaned = cleaned.lstrip("./")
        if cleaned.startswith("../images/"):
            path = cleaned
        elif cleaned.startswith("images/"):
            path = f"../{cleaned}"
        else:
            path = f"../images/{Path(cleaned).name}"
        return f"{attr}={quote}{path}{quote}"

    return re.sub(
        r"""\b(href|xlink:href)=(["'])([^"']+)\2""",
        _fix,
        svg,
        flags=re.I,
    )


def _wrap_svg_as_slide_html(svg_body: str) -> str:
    """Embed SVG into a 1920×1080 stage (Admin / public preview canvas)."""
    body = svg_body.strip()
    if body.startswith("<?xml"):
        body = re.sub(r"^<\?xml[^>]*\?>\s*", "", body, count=1, flags=re.I)
    # Force SVG to fill the preview stage regardless of intrinsic viewBox size.
    if re.search(r"<svg\b", body, flags=re.I):
        body = re.sub(
            r"<svg\b([^>]*)>",
            lambda m: (
                "<svg"
                + re.sub(r'\s(width|height)=("[^"]*"|\'[^\']*\')', "", m.group(1), flags=re.I)
                + ' width="1920" height="1080" preserveAspectRatio="xMidYMid meet">'
            ),
            body,
            count=1,
            flags=re.I,
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=1920"/>\n'
        '<link rel="stylesheet" href="../theme.css"/>\n'
        "<style>\n"
        "html,body{margin:0;padding:0;background:#111;overflow:hidden}\n"
        ".stage{width:1920px;height:1080px;position:relative;overflow:hidden}\n"
        ".stage svg{display:block;width:1920px;height:1080px}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="stage" data-pptx-export-fallback="svg">\n'
        f"{body}\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


def _write_svg_fallback_package(
    project: Path,
    *,
    template_id: str,
    label_zh: str,
    out_root: Path,
    slides: list[dict[str, Any]],
    export_error: str,
    usage: Any,
    log: LogFn | None = None,
    palette: dict[str, Any] | None = None,
) -> Path:
    """When svg_to_pptx fails under soft/skip, still land a reviewable pack."""
    from webppt_agent.templates.types import SlideSpec, TemplatePackage
    from webppt_agent.templates.write import write_package

    svg_dir = project / "svg_output"
    svg_files = sorted(svg_dir.glob("*.svg"))
    if not svg_files:
        raise RuntimeError(f"SVG fallback 失败：无 svg 文件（{svg_dir}）")

    err_brief = re.sub(r"\s+", " ", str(export_error)).strip()
    if len(err_brief) > 240:
        err_brief = err_brief[:237] + "…"

    slide_specs: list[SlideSpec] = []
    seen: dict[str, int] = {}
    for idx, path in enumerate(svg_files):
        layout = _layout_from_svg_filename(path.name)
        n = seen.get(layout, 0) + 1
        seen[layout] = n
        if n > 1:
            layout = f"{layout}-{n}"
        plan_slide = slides[idx] if idx < len(slides) else {}
        title = str(
            plan_slide.get("title")
            or plan_slide.get("page_title")
            or layout
        )
        raw = path.read_text(encoding="utf-8")
        html = _wrap_svg_as_slide_html(_rewrite_svg_image_hrefs_for_package(raw))
        slide_specs.append(
            SlideSpec(
                layout=layout,
                title=title,
                description=f"SVG 预览回退 · {path.name}",
                html=html,
            )
        )

    bg = str((palette or {}).get("bg") or (palette or {}).get("background") or "#111111")
    fg = str((palette or {}).get("text") or (palette or {}).get("fg") or "#FFFFFF")
    theme_css = (
        f":root{{--bg:{bg};--text:{fg};}}\n"
        "html,body{margin:0;background:var(--bg);color:var(--text);}\n"
    )

    package = TemplatePackage(
        template_id=template_id,
        label_zh=label_zh or template_id,
        label_en=template_id,
        description_zh=(
            f"PPTX 导出失败，已写入 SVG 预览包（共 {len(slide_specs)} 页）；"
            "须人工校验后再通过。不可直接当作标准 DrawingML 转换结果。"
        ),
        description_en=(
            f"PPTX export failed; SVG preview package ({len(slide_specs)} slides) "
            "pending manual review."
        ),
        theme_css=theme_css,
        slides=slide_specs,
        warnings=[
            "export_fallback=svg：svg_to_pptx / 转包失败后的预览入库",
            f"export_error={err_brief}",
        ],
        source_kind="ppt-master-svg-fallback",
        source_file=str(project),
        format="ppt-master",
        visual_spec_outline="ppt-master svg-fallback · pending review",
        usage=usage.to_dict() if hasattr(usage, "to_dict") else None,
    )

    out_dir = (out_root / template_id).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    write_package(package, out_dir, skip_images=True)

    # Copy raster assets referenced by SVGs (best-effort).
    src_images = project / "images"
    dst_images = out_dir / "images"
    dst_images.mkdir(parents=True, exist_ok=True)
    if src_images.is_dir():
        for img in src_images.iterdir():
            if img.is_file():
                shutil.copy2(img, dst_images / img.name)

    meta_path = out_dir / "template.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["status"] = "pending"
    meta["render"] = "svg-fallback"
    meta["review"] = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "note": (
            "PPTX 导出失败，已用 SVG 预览入库；人工确认无误后再「通过」。"
            f" 原因：{err_brief}"
        ),
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _log(log, f"[html-slide] fallback SVG package → {out_dir} (pending review)")
    return out_dir


def _progress(done: int, total: int, ok: int, fail: int, tid: str, status: str) -> str:
    return (
        f"[progress] done={done} total={total} ok={ok} fail={fail} "
        f"skip=0 id={tid} status={status}"
    )


def run_one_package(
    prompt: str,
    *,
    pages: int = 7,
    visual_style: str = "dark-tech",
    template_id: str | None = None,
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool | None = None,
    palette_refine: bool | None = None,
    slide_concurrency: int = 4,
    fast_preview: bool = False,
    svg_repair: bool = True,
    quality_gate: str = "soft",
    strip_unsupported: bool = True,
    log: LogFn | None = None,
) -> dict[str, Any]:
    from webppt_agent.ppt_master.palette import (
        apply_palette_to_plan,
        palette_refine_enabled,
    )

    load_env()
    assert_ppt_master_ready()
    use_mock = is_mock() if mock is None else bool(mock)
    enable_images = _want_images(skip_images=skip_images) and not use_mock
    if skip_images is True:
        os.environ["AGENT_SKIP_IMAGE"] = "1"
    elif skip_images is False:
        os.environ.pop("AGENT_SKIP_IMAGE", None)
    do_palette_refine = palette_refine_enabled(palette_refine)
    if palette_refine is True:
        os.environ["AGENT_PALETTE_REFINE"] = "1"
    elif palette_refine is False:
        os.environ["AGENT_PALETTE_REFINE"] = "0"
    pages = max(3, min(12, int(pages)))
    out_root = (out_root or (repo_root() / "agent-output")).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    gate_mode = _normalize_quality_gate(quality_gate, fast_preview=fast_preview)
    enable_repair = bool(svg_repair) and gate_mode != "skip"
    do_strip = bool(strip_unsupported)

    _log(log, f"[ppt-master] skill={skill_dir()}")
    _log(
        log,
        f"[ppt-master] mock={use_mock} pages={pages} style={visual_style or 'dark-tech'} "
        f"images={enable_images} palette_refine={do_palette_refine} "
        f"quality_gate={gate_mode} "
        f"svg_repair={enable_repair} strip_unsupported={do_strip}",
    )

    with track_usage() as usage:
        if not use_mock:
            cfg0 = llm_config()
            usage.set_models(
                page_model=cfg0.model,
                image_model=(os.environ.get("IMAGE_MODEL") or "").strip() or None,
            )

        plan, plan_meta = _build_plan(
            prompt=prompt,
            pages=pages,
            visual_style=visual_style or "dark-tech",
            use_mock=use_mock,
            log=log,
            enable_images=enable_images,
        )
        plan = force_plan_style(plan, visual_style or "dark-tech")
        plan, palette_notes = apply_palette_to_plan(
            plan, enabled=do_palette_refine
        )
        _log(
            log,
            f"[plan] candidates={plan_meta['candidates']} selected={plan_meta['selected']} "
            f"score={plan_meta['score']} style={plan.get('visual_style')}",
        )
        if do_palette_refine:
            _log(log, f"[palette] refine {' | '.join(palette_notes) or 'ok'}")
        slides = plan["slides"]
        tid = _resolve_pack_name(
            label_zh=plan.get("label_zh"),
            template_id=template_id or plan.get("template_id"),
            prompt=prompt,
            out_root=out_root,
            visual_style=visual_style or str(plan.get("visual_style") or ""),
        )
        plan["template_id"] = tid
        if not str(plan.get("label_zh") or "").strip() or not _has_cjk(
            str(plan.get("label_zh") or "")
        ):
            plan["label_zh"] = tid
        palette = plan.get("palette") if isinstance(plan.get("palette"), dict) else {}

        project = _init_project(f"webppt-{tid}"[:40], log)
        svg_dir = project / "svg_output"
        svg_dir.mkdir(parents=True, exist_ok=True)
        images_dir = project / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        image_refs = _assign_plan_images(slides, enable=enable_images)
        if image_refs:
            style_hint = " ".join(
                [
                    str(plan.get("visual_style") or visual_style or ""),
                    str(plan.get("label_zh") or tid),
                    str(plan.get("product") or ""),
                ]
            ).strip()
            with use_usage(usage):
                _materialize_plan_images(
                    project,
                    image_refs,
                    style_hint=style_hint,
                    palette=palette,
                    log=log,
                )
        else:
            _log(log, "[images] none requested")

        # Keep the human-readable copy on disk, but send a compact, stable
        # authoring context to every page call.  The full plan is still
        # preserved in plan.json/plan_lock.json for reproducibility.
        plan_json = prompts.compact_plan_json(plan)
        plan_file_json = json.dumps(plan, ensure_ascii=False, indent=2)
        (project / "plan.json").write_text(plan_file_json + "\n", encoding="utf-8")
        (project / "plan_lock.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "locked_at": datetime.now().isoformat(timespec="seconds"),
                    "creative": plan_meta,
                    "template_id": tid,
                    "visual_style": plan.get("visual_style"),
                    "palette": palette,
                    "images": image_refs,
                    "slides": slides,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        allowed_images = set(image_refs.keys())
        # Per-page checking starts as soon as a page is returned.  Normalize
        # mislabeled image files first so the checker does not send an image
        # container problem back to the layout repair path.
        _repair_mismatched_image_files(images_dir, log=log)

        def gen_one(idx: int, slide: dict[str, Any]) -> tuple[str, str]:
            from webppt_agent.ppt_master.image_fusion import (
                audit_svg_image_fusion,
                fusion_repair_brief,
            )

            file_name = str(slide.get("file") or f"{idx:02d}_slide.svg")
            if not file_name.endswith(".svg"):
                file_name += ".svg"
            prepared = str(slide.get("image_file") or "").strip() or None
            if prepared and prepared not in allowed_images:
                prepared = None
            if prepared and not (images_dir / prepared).is_file():
                prepared = None
            with use_usage(usage):
                if use_mock:
                    svg = _mock_svg(slide, palette)
                else:
                    cfg = llm_config()
                    pool = make_client_pool(cfg)
                    fusion_critique = ""
                    svg = ""
                    for attempt in range(1, 3):
                        raw = chat_text(
                            pool=pool,
                            model=cfg.model,
                            system=prompts.SYSTEM_SVG,
                            user=prompts.user_svg(
                                plan_json=plan_json,
                                slide=slide,
                                page_index=idx,
                                page_total=len(slides),
                                visual_style=str(
                                    plan.get("visual_style")
                                    or visual_style
                                    or "dark-tech"
                                ),
                                prepared_image=prepared,
                                image_hint=str(slide.get("image_hint") or ""),
                                fusion_critique=fusion_critique,
                            ),
                            temperature=0.45 if attempt == 1 else 0.25,
                        )
                        svg = _strip_svg(raw)
                        svg = _scrub_svg_image_refs(
                            svg, allowed=allowed_images, images_dir=images_dir
                        )
                        issues = audit_svg_image_fusion(
                            svg, prepared_image=prepared
                        )
                        compat_issues = generation_compatibility_issues(svg)
                        if compat_issues:
                            issues = list(issues) + [
                                f"native-export compatibility: {item}"
                                for item in compat_issues
                            ]
                        if not issues:
                            break
                        fusion_critique = fusion_repair_brief(issues)
                        _log(
                            log,
                            f"[svg] fusion retry {attempt}/2 {file_name}: "
                            f"{issues[0]}",
                        )
            return file_name, svg

        workers = max(1, min(int(slide_concurrency or 4), len(slides)))
        _log(log, f"[svg] generating {len(slides)} pages concurrency={workers}")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(gen_one, i, s): i for i, s in enumerate(slides, 1)}
            for fut in as_completed(futs):
                i = futs[fut]
                file_name, svg = fut.result()
                cleaned = sanitize_svg_text(svg)
                cleaned = _scrub_svg_image_refs(
                    cleaned, allowed=allowed_images, images_dir=images_dir
                )
                # 最终再扫一遍融合问题（仅告警；重试已在 gen_one）
                from webppt_agent.ppt_master.image_fusion import audit_svg_image_fusion

                slide = slides[i - 1] if 0 <= i - 1 < len(slides) else {}
                prepared = str(slide.get("image_file") or "").strip() or None
                if prepared and prepared not in allowed_images:
                    prepared = None
                left = audit_svg_image_fusion(cleaned, prepared_image=prepared)
                if left:
                    _log(log, f"[svg] fusion WARN {file_name}: {left[0]}")
                (svg_dir / file_name).write_text(cleaned, encoding="utf-8")
                _log(log, f"[svg] wrote {file_name}")
                if gate_mode != "skip":
                    with use_usage(usage):
                        _preflight_generated_page(
                            project,
                            file_name,
                            slide,
                            log,
                            enable_repair=enable_repair and not use_mock,
                        )

        drafts = repo_root() / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        pptx_path = drafts / f"{tid}.pptx"
        # Safety: Maizi (and similar) may return JPEG under a .png name; quality
        # checker / svg_to_pptx reject extension mismatches as "corrupt".
        _repair_mismatched_image_files(images_dir, log=log)
        export_fallback = False
        try:
            with use_usage(usage):
                gate_passed = _export_pptx(
                    project,
                    pptx_path,
                    slides,
                    plan_json,
                    log,
                    enable_repair=enable_repair,
                    quality_gate=gate_mode,
                    strip_unsupported=do_strip,
                )
            if gate_mode == "skip":
                quality_gate = "skipped"
            elif gate_passed:
                quality_gate = "passed"
            elif enable_repair:
                quality_gate = "soft-pass-after-repair"
            else:
                quality_gate = "gate-fail-no-repair"
            _log(log, f"[pptx] {pptx_path}")

            pack_dir = _convert_to_html_slide(
                pptx_path,
                template_id=tid,
                out_root=out_root,
                log=log,
                pack_format="ppt-master",
            )
        except Exception as exc:
            if gate_mode == "strict":
                raise
            _log(
                log,
                f"[export] PPTX/转包失败 → 写入 SVG 预览包供人工审核：{exc}",
            )
            pack_dir = _write_svg_fallback_package(
                project,
                template_id=tid,
                label_zh=str(plan.get("label_zh") or tid),
                out_root=out_root,
                slides=slides if isinstance(slides, list) else [],
                export_error=str(exc),
                usage=usage,
                log=log,
                palette=palette if isinstance(palette, dict) else {},
            )
            quality_gate = "export-fallback-svg"
            export_fallback = True
        if not export_fallback:
            _write_usage_into_template(pack_dir, usage)
            # Mark provenance for A/B with HTML render packs
            try:
                meta_path = pack_dir / "template.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    meta["render"] = "svg"
                    meta_path.write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
            except (OSError, json.JSONDecodeError):
                pass
        usage_dict = usage.to_dict()
        page_tokens = int(usage_dict.get("page_tokens") or 0)
        image_tokens = int(usage_dict.get("image_tokens") or 0)
        image_count = int((usage_dict.get("image") or {}).get("images") or 0)
        _log(
            log,
            f"[html-slide] {pack_dir} format=ppt-master "
            f"{'render=svg-fallback ' if export_fallback else ''}"
            f"page_tokens={page_tokens} image_count={image_count} image_tokens={image_tokens}",
        )
        return {
            "ok": True,
            "template_id": tid,
            "project": str(project),
            "pptx": str(pptx_path) if not export_fallback else None,
            "output_dir": str(pack_dir),
            "quality_gate": quality_gate,
            "export_fallback": "svg" if export_fallback else None,
            "page_tokens": page_tokens,
            "image_count": image_count,
            "image_tokens": image_tokens,
            "status": "pending",
            "review_state": "pending_review",
            "format": "ppt-master",
            "render": "svg-fallback" if export_fallback else "svg",
        }


def run_ppt_master_pipeline(
    prompt: str,
    *,
    count: int = 1,
    pages: int = 7,
    visual_style: str = "dark-tech",
    out_root: Path | None = None,
    mock: bool | None = None,
    skip_images: bool | None = None,
    palette_refine: bool | None = None,
    slide_concurrency: int = 4,
    fast_preview: bool = False,
    svg_repair: bool = True,
    quality_gate: str = "soft",
    strip_unsupported: bool = True,
    log: LogFn | None = None,
) -> list[dict[str, Any]]:
    """批量：每包独立跑一遍（仅 SVG → PPTX → 模板包）。"""
    total = max(1, min(20, int(count)))
    rows: list[dict[str, Any]] = []
    ok = fail = 0
    for i in range(1, total + 1):
        hint = prompt.strip()
        if total > 1:
            hint = f"{hint}\n\n（批量 #{i}/{total}，请换一套互异版式与文案。）"
        tid_hint = None
        try:
            row = run_one_package(
                hint or "科技产品发布会，暗色科技风，有冲击力封面与数据页",
                pages=pages,
                visual_style=visual_style,
                template_id=tid_hint,
                out_root=out_root,
                mock=mock,
                skip_images=skip_images,
                palette_refine=palette_refine,
                slide_concurrency=slide_concurrency,
                fast_preview=fast_preview,
                svg_repair=svg_repair,
                quality_gate=quality_gate,
                strip_unsupported=strip_unsupported,
                log=log,
            )
            row["render"] = "svg"
            ok += 1
            rows.append(row)
            _log(log, _progress(i, total, ok, fail, row["template_id"], "ok"))
        except Exception as e:
            fail += 1
            err = str(e)
            rows.append({"ok": False, "error": err, "template_id": None, "render": "svg"})
            _log(log, f"[fail] package {i}/{total}: {err}")
            _log(log, _progress(i, total, ok, fail, f"pkg-{i}", "fail"))
        time.sleep(0.05)
    return rows
