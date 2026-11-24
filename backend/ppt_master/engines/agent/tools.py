"""工具表（Harness 组件）：模型能动用的全部能力。

设计原则（见设计文档 §6）：

- **不重写能力，只装门把手**：每个写工具内部复用旧管线已有的校验函数，
  门禁长在工具里，模型绕不过去。
- **返回可操作的诊断**：拒绝时给原文错误（"title/body 重叠 34px"），
  而不是"请重试"。这是 agent 强于旧管线的机制来源。
- **锁死项不做成工具**：样式卡只读、导出只有唯一通道、验收只在 finish。

工具分两组，按引擎模式注册：

- 两组共有：list_styles / read_style_card / write_plan / read_plan /
  delete_page / insert_page / finish
- full 模式追加：write_page / read_page / edit_page / check_page / check_all /
  measure_render / export_pptx
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ppt_master.engines.agent import style_guard
from ppt_master.engines.agent.workspace import Workspace, WorkspaceError, _safe_rel
from ppt_master.engines.base import SkillBridge

Handler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# 规划类工具
# ---------------------------------------------------------------------------


def _tool_list_styles(bridge: SkillBridge) -> Tool:
    def handler(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            entries = bridge.catalog()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"读取风格目录失败：{exc}"}
        rows = [
            {
                "id": item.get("id"),
                "label_zh": item.get("label_zh"),
                "family": item.get("family") or item.get("group_zh"),
            }
            for item in entries
        ]
        return {"ok": True, "styles": rows, "count": len(rows)}

    return Tool(
        name="list_styles",
        description="列出 PPT Master 已有的视觉风格卡（只读）。先看目录再决定用哪个。",
        parameters=_obj({}),
        handler=handler,
    )


def _tool_read_style_card(bridge: SkillBridge) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        style = str(args.get("style") or "").strip()
        if not style:
            return {"ok": False, "error": "缺少 style"}
        try:
            card = bridge.style_card(style)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"读取风格卡失败：{exc}"}
        if not (card or "").strip():
            return {"ok": False, "error": f"风格卡 {style} 为空或不存在"}
        return {"ok": True, "style": style, "card": card}

    return Tool(
        name="read_style_card",
        description=(
            "读取某张视觉风格卡的正文（只读，不可修改）。"
            "写 plan 之前必须先读，用它规定的造型语言描述版面。"
        ),
        parameters=_obj({"style": {"type": "string", "description": "风格 id，如 dark-tech"}}, ["style"]),
        handler=handler,
    )


def _tool_write_plan(ws: Workspace, prompt: str) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        plan = args.get("plan") if isinstance(args.get("plan"), dict) else args
        if not isinstance(plan, dict) or not plan:
            return {"ok": False, "error": "plan 为空"}
        candidate = dict(plan)

        # 页数约束按模式分流——这是 agent 的核心自由度，必须显式处理：
        #   plan 模式：页数必须等于目标（下游流水线按 preset_plan 严格校验）
        #   full 模式：允许在 3..12 内浮动（"这页该拆两页"是真实需求）
        declared = len([s for s in (candidate.get("slides") or []) if isinstance(s, dict)])
        if ws.mode == "full":
            if not 3 <= declared <= 12:
                return {
                    "ok": False,
                    "stage": "shape",
                    "blocking": [f"页数 {declared} 超出 3..12 范围"],
                }
        elif declared != ws.pages:
            return {
                "ok": False,
                "stage": "shape",
                "blocking": [
                    f"页数 {declared} != 目标 {ws.pages}；"
                    "plan 模式页数固定（要调整页数请用 full 模式）"
                ],
            }

        # 门禁 1：复用旧管线的几何/名册校验（先自愈机械错误，再复验）
        from ppt_master.pipeline import _validate_plan, repair_plan_layout

        try:
            _validate_plan(candidate, declared)
        except RuntimeError as exc:
            message = str(exc)
            if any(t in message for t in ("clearance", "安全区", "无有效文字内框")):
                repair_plan_layout(candidate)
                try:
                    _validate_plan(candidate, declared)
                except RuntimeError as exc2:
                    return {"ok": False, "stage": "shape", "blocking": [str(exc2)]}
            else:
                return {"ok": False, "stage": "shape", "blocking": [message]}

        # 门禁 2：样式一致性（palette / 命名 / 结构指纹）
        gate = style_guard.check_plan(candidate, ws.style, prompt)
        if not gate["ok"]:
            return {
                "ok": False,
                "stage": "style",
                "blocking": gate["blocking"],
                "warnings": gate["warnings"],
            }

        ws.save_plan(candidate)
        return {
            "ok": True,
            "slides": len(candidate.get("slides") or []),
            "warnings": gate["warnings"],
        }

    return Tool(
        name="write_plan",
        description=(
            "提交整册规划（页表）。必须包含 template_id / label_zh / palette / slides。"
            "每页需要 file / role / title / core_message / geometry / layout_regions / visual_hook。"
            "layout_regions 每项形如 "
            '{"id":"title","role":"page-title","bounds":[x,y,w,h],'
            '"padding":[top,right,bottom,left],"clearance":12}——'
            "bounds 与 padding 必须是四值数组（不是对象、不是单个数字），clearance 是数字。"
            "不通过时会返回具体 blocking 原因，按提示修正后重试。"
        ),
        parameters=_obj(
            {
                "template_id": {"type": "string"},
                "label_zh": {"type": "string"},
                "product": {"type": "string"},
                "visual_style": {"type": "string"},
                "palette": {"type": "object"},
                "slides": {"type": "array", "items": {"type": "object"}},
            },
            ["slides"],
        ),
        handler=handler,
    )


def _tool_read_plan(ws: Workspace) -> Tool:
    def handler(_args: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "plan": ws.load_plan()}
        except (WorkspaceError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}

    return Tool(
        name="read_plan",
        description="读取当前 plan.json。状态外置，需要时再读，不要凭记忆猜。",
        parameters=_obj({}),
        handler=handler,
    )


# ---------------------------------------------------------------------------
# 页面名册工具（两种模式都有：页数自由是 agent 的核心自由度）
# ---------------------------------------------------------------------------


def _tool_delete_page(ws: Workspace) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("file") or "").strip()
        if not rel:
            return {"ok": False, "error": "缺少 file"}
        try:
            rel = _safe_rel(rel)
            plan = ws.load_plan()
        except (WorkspaceError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}
        slides = [s for s in (plan.get("slides") or []) if isinstance(s, dict)]
        remaining = [s for s in slides if str(s.get("file") or "") != rel]
        if len(remaining) == len(slides):
            return {"ok": False, "error": f"plan 里没有这一页：{rel}"}
        if len(remaining) < 3:
            return {"ok": False, "error": f"删除后只剩 {len(remaining)} 页，少于 3 页下限"}
        plan["slides"] = remaining
        ws.save_plan(plan)
        ws.delete_page(rel)
        ws.snapshot(label=f"delete {rel}")
        return {"ok": True, "slides": len(remaining), "deleted": rel}

    return Tool(
        name="delete_page",
        description="从 plan 与磁盘删除一整页（如删除重复的过渡页）。不得少于 3 页。",
        parameters=_obj({"file": {"type": "string"}}, ["file"]),
        handler=handler,
    )


def _tool_insert_page(ws: Workspace) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        slide = args.get("slide")
        if not isinstance(slide, dict):
            return {"ok": False, "error": "缺少 slide 对象"}
        after = str(args.get("after") or "").strip()
        try:
            plan = ws.load_plan()
        except (WorkspaceError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}
        slides = [s for s in (plan.get("slides") or []) if isinstance(s, dict)]
        if len(slides) >= 12:
            return {"ok": False, "error": "已达 12 页上限"}
        rel = str(slide.get("file") or "").strip()
        if not rel:
            return {"ok": False, "error": "slide.file 必填"}
        if any(str(s.get("file") or "") == rel for s in slides):
            return {"ok": False, "error": f"页面文件名重复：{rel}"}
        index = len(slides)
        if after:
            for i, item in enumerate(slides):
                if str(item.get("file") or "") == after:
                    index = i + 1
                    break
            else:
                return {"ok": False, "error": f"after 指向的页面不存在：{after}"}
        slides.insert(index, slide)
        plan["slides"] = slides
        ws.save_plan(plan)
        ws.snapshot(label=f"insert {rel}")
        return {"ok": True, "slides": len(slides), "index": index}

    return Tool(
        name="insert_page",
        description=(
            "在指定页之后插入一页（发现某页内容过多、需要拆成两页时用）。"
            "slide 需要与 write_plan 里单页相同的字段。"
        ),
        parameters=_obj(
            {
                "after": {"type": "string", "description": "插到这一页之后；省略则追加到末尾"},
                "slide": {"type": "object"},
            },
            ["slide"],
        ),
        handler=handler,
    )


# ---------------------------------------------------------------------------
# SVG 工具（仅 full 模式）
# ---------------------------------------------------------------------------


def _allowed_images(ws: Workspace) -> set[str]:
    try:
        return {p.name for p in (ws.root / "images").glob("*") if p.is_file()}
    except OSError:
        return set()


def _planned_image(ws: Workspace, rel: str, allowed: set[str]) -> str | None:
    """本页在 plan 里登记的配图文件名；没登记或文件不存在则 None。"""
    try:
        plan = ws.load_plan()
    except (WorkspaceError, OSError):
        return None
    for slide in plan.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        try:
            if _safe_rel(str(slide.get("file") or "")) != rel:
                continue
        except WorkspaceError:
            continue
        name = str(slide.get("image_file") or "").strip()
        if name and name in allowed and (ws.root / "images" / name).is_file():
            return name
        return None
    return None


def _tool_prepare_images(
    ws: Workspace,
    *,
    enabled: bool,
    log: Callable[[str], None] | None = None,
) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        if not enabled:
            return {
                "ok": False,
                "error": "本次任务关闭了配图（skipImage / mock），所有页面只能用 SVG 画版面",
            }
        try:
            plan = ws.load_plan()
        except (WorkspaceError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        slides = plan.get("slides")
        if not isinstance(slides, list) or not slides:
            return {"ok": False, "error": "plan 里没有 slides，先调用 write_plan"}

        from ppt_master.pipeline import _assign_plan_images, _materialize_plan_images

        try:
            refs = _assign_plan_images(slides, enable=True)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"分配配图失败：{exc}"}
        if not refs:
            ws.save_plan(plan)
            return {
                "ok": True,
                "images": 0,
                "pages": [],
                "note": "没有任何页面需要配图：全部用 SVG 形状与文字完成版面，禁止 <image>",
            }

        style_hint = " ".join(
            [
                str(plan.get("visual_style") or ws.style or ""),
                str(plan.get("label_zh") or ""),
                str(plan.get("product") or ""),
            ]
        ).strip()
        palette = plan.get("palette") if isinstance(plan.get("palette"), dict) else {}
        try:
            _materialize_plan_images(
                ws.root, refs, style_hint=style_hint, palette=palette, log=log
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"生图失败：{exc}"}

        # 生图后回填 image_file / image_aspect，write_page 与交付阶段都读它。
        ws.save_plan(plan)
        present = _allowed_images(ws)
        pages = [
            {
                "file": s.get("file"),
                "image_file": s.get("image_file"),
                "image_aspect": s.get("image_aspect"),
                "image_role": s.get("image_role"),
            }
            for s in slides
            if isinstance(s, dict) and s.get("image_file")
        ]
        missing = [p["file"] for p in pages if p["image_file"] not in present]
        return {
            "ok": not missing,
            "images": len(refs),
            "ready": len(pages) - len(missing),
            "pages": pages,
            "missing": missing,
            "hint": (
                "有配图的页必须引用一次且只引用这一个文件名："
                '<image href="../images/<image_file>" preserveAspectRatio="xMidYMid slice" '
                'data-pptx-role="decoration" data-slot-type="image" data-slot-role="hero-image"/>；'
                "无配图的页禁止任何 <image>。"
            ),
        }

    return Tool(
        name="prepare_images",
        description=(
            "按 plan 里的 need_image / 页面角色生成配图并写入 images/，"
            "然后把每页的 image_file 回填进 plan 并返回给你。"
            "写完 plan、开始画页面前调用一次；有配图的页必须引用返回的文件名，"
            "否则 write_page 的融合检查会拒绝。"
        ),
        parameters=_obj({}),
        handler=handler,
    )


def _tool_write_page(ws: Workspace) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("file") or "").strip()
        svg = str(args.get("svg") or "")
        if not rel or not svg.strip():
            return {"ok": False, "error": "缺少 file 或 svg"}
        try:
            rel = _safe_rel(rel)
        except WorkspaceError as exc:
            return {"ok": False, "error": str(exc)}

        # 与旧管线 gen_one 完全相同的门禁顺序
        from ppt_master.image_fusion import audit_svg_image_fusion
        from ppt_master.pipeline import _scrub_svg_image_refs, authored_svg_reject_reason
        from ppt_master.sanitize import (
            generation_compatibility_issues,
            is_well_formed_svg,
            sanitize_svg_text,
        )

        cleaned = sanitize_svg_text(svg, strip_unsupported=True)
        if not is_well_formed_svg(cleaned):
            return {"ok": False, "stage": "xml", "blocking": ["Invalid XML：输出必须是合法 SVG"]}
        reason = authored_svg_reject_reason(cleaned)
        if reason:
            return {"ok": False, "stage": "empty", "blocking": [reason]}

        allowed = _allowed_images(ws)
        cleaned = _scrub_svg_image_refs(
            cleaned, allowed=allowed, images_dir=ws.root / "images"
        )
        # plan 里给本页登记过配图就必须引用它：prepared_image 是 keyword-only。
        # 没登记（或生图没成功）时传 None —— 此时页面里任何 <image> 都已被上面的
        # _scrub_svg_image_refs 清掉，语义是"本页无配图"。
        prepared = _planned_image(ws, rel, allowed)
        issues = list(audit_svg_image_fusion(cleaned, prepared_image=prepared))
        issues += [
            f"native-export compatibility: {item}"
            for item in generation_compatibility_issues(cleaned)
        ]
        if issues:
            return {
                "ok": False,
                "stage": "fusion",
                "blocking": issues[:8],
                "hint": "修掉这些再提交；可通过 read_page 读回已保存的版本。",
            }

        ws.write_page(rel, cleaned)
        ws.snapshot(label=f"write {rel}")
        return {"ok": True, "file": rel, "bytes": len(cleaned)}

    return Tool(
        name="write_page",
        description=(
            "写入/覆盖某一页的 SVG。会立刻做 XML 合法性、空壳、图文融合、"
            "原生导出兼容性四道检查；不通过时返回具体 blocking 原因且不落盘。"
        ),
        parameters=_obj(
            {"file": {"type": "string"}, "svg": {"type": "string"}},
            ["file", "svg"],
        ),
        handler=handler,
    )


def _tool_read_page(ws: Workspace) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            rel = _safe_rel(str(args.get("file") or ""))
            return {"ok": True, "file": rel, "svg": ws.read_page(rel)}
        except (WorkspaceError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    return Tool(
        name="read_page",
        description="读回某一页当前的 SVG 文本（状态外置，不占常驻上下文）。",
        parameters=_obj({"file": {"type": "string"}}, ["file"]),
        handler=handler,
    )


def _tool_edit_page(ws: Workspace) -> Tool:
    """小步编辑：字面量替换。比整页重写便宜一个数量级。"""

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            rel = _safe_rel(str(args.get("file") or ""))
            text = ws.read_page(rel)
        except (WorkspaceError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        ops = args.get("ops")
        if not isinstance(ops, list) or not ops:
            return {"ok": False, "error": "ops 必须是非空数组"}
        applied = 0
        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                return {"ok": False, "error": f"ops[{i}] 不是对象"}
            find = str(op.get("find") or "")
            replace = str(op.get("replace") or "")
            if not find:
                return {"ok": False, "error": f"ops[{i}].find 为空"}
            if find not in text:
                return {
                    "ok": False,
                    "error": f"ops[{i}].find 在页面中不存在（可能已被改动）；先 read_page 再改",
                    "need_read": True,
                }
            text = text.replace(find, replace)
            applied += 1

        from ppt_master.sanitize import is_well_formed_svg, sanitize_svg_text

        cleaned = sanitize_svg_text(text, strip_unsupported=True)
        if not is_well_formed_svg(cleaned):
            return {"ok": False, "error": "编辑后 SVG 不再合法；已放弃本次修改"}
        ws.write_page(rel, cleaned)
        ws.snapshot(label=f"edit {rel}")
        return {"ok": True, "file": rel, "applied": applied}

    return Tool(
        name="edit_page",
        description=(
            "对已存在页面做字面量替换（小步修改）。"
            "ops 形如 [{find:'原文本/片段', replace:'新文本'}]。"
            "找不到 find 时说明页面已变，需要先 read_page。"
        ),
        parameters=_obj(
            {
                "file": {"type": "string"},
                "ops": {
                    "type": "array",
                    "items": _obj(
                        {"find": {"type": "string"}, "replace": {"type": "string"}},
                        ["find", "replace"],
                    ),
                },
            },
            ["file", "ops"],
        ),
        handler=handler,
    )


def _tool_check_page(ws: Workspace, bridge: SkillBridge) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("file") or "").strip()
        if not rel:
            return {"ok": False, "error": "缺少 file"}
        try:
            rel = _safe_rel(rel)
            ws.read_page(rel)
        except (WorkspaceError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
        from ppt_master.engines.agent.acceptance import _page_errors

        try:
            passed, report = bridge.quality_report(_project(ws), file_name=Path(rel).name)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"质检执行失败：{exc}"}
        if passed:
            return {"ok": True, "file": rel, "blocking": []}
        errors = _page_errors(report, Path(rel).name) or _page_errors(report)
        return {
            "ok": False,
            "file": rel,
            "blocking": errors[:12] or ["质检未通过（无页面级错误信息）"],
        }

    return Tool(
        name="check_page",
        description="对单页跑 PPT Master 质检，返回具体的 blocking 错误（不信任模型自评）。",
        parameters=_obj({"file": {"type": "string"}}, ["file"]),
        handler=handler,
    )


def _tool_check_all(ws: Workspace, bridge: SkillBridge) -> Tool:
    def handler(_args: dict[str, Any]) -> dict[str, Any]:
        from ppt_master.engines.agent.acceptance import _page_errors

        try:
            passed, report = bridge.quality_report(_project(ws))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"质检执行失败：{exc}"}
        if passed:
            return {"ok": True, "blocking": []}
        return {"ok": False, "blocking": _page_errors(report)[:12] or ["质检未通过"]}

    return Tool(
        name="check_all",
        description="对整册跑一次 PPT Master 质检（final stage），返回逐条 blocking 错误。",
        parameters=_obj({}),
        handler=handler,
    )


def _tool_measure_render(ws: Workspace) -> Tool:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        pack = str(args.get("pack_dir") or "").strip()
        target = Path(pack) if pack else ws.root
        if not (target / "slides").is_dir():
            return {
                "ok": False,
                "error": (
                    "还没有 HTML 页包可量。measure_render 只能作用于已导出的 html-slide 包；"
                    "当前阶段请用 check_all 的逐条错误作为依据。"
                ),
            }
        from templates.render_check import check_package_render

        try:
            result = check_package_render(target)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"渲染测量失败：{exc}"}
        issues = result.get("issues") or []
        return {
            "ok": not issues,
            "engine": result.get("engine"),
            "pages": result.get("pages"),
            "issues": issues[:12],
            "note": result.get("error"),
        }

    return Tool(
        name="measure_render",
        description=(
            "用真实 Chrome 量渲染溢出（能抓到字体回退、letter-spacing 取整这类"
            "质检器抓不到的问题）。只能作用于已导出的 html-slide 包。"
        ),
        parameters=_obj({"pack_dir": {"type": "string"}}),
        handler=handler,
    )


def _project(ws: Workspace) -> Path:
    return ws.project if ws.project is not None else ws.root


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


def build_tools(
    ws: Workspace,
    *,
    bridge: SkillBridge,
    prompt: str,
    mode: str,
    images_enabled: bool = False,
    log: Callable[[str], None] | None = None,
) -> dict[str, Tool]:
    """按模式组装工具表。

    ``images_enabled`` 由调用方按 skipImage / mock 决定，只影响
    ``prepare_images`` 是否可用——关掉时它仍注册，但调用会直接说明原因，
    比"工具不存在"更容易让模型改走纯 SVG 版面。
    """
    tools: list[Tool] = [
        _tool_list_styles(bridge),
        _tool_read_style_card(bridge),
        _tool_write_plan(ws, prompt),
        _tool_read_plan(ws),
        _tool_delete_page(ws),
        _tool_insert_page(ws),
    ]
    if mode == "full":
        tools += [
            _tool_prepare_images(ws, enabled=images_enabled, log=log),
            _tool_write_page(ws),
            _tool_read_page(ws),
            _tool_edit_page(ws),
            _tool_check_page(ws, bridge),
            _tool_check_all(ws, bridge),
            _tool_measure_render(ws),
        ]
    return {tool.name: tool for tool in tools}
