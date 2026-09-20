from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from webppt_agent import __version__
from webppt_agent.config import is_mock, llm_config, load_env


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webppt-agent",
        description="PPT Master：规范 SVG → 原生 PPTX → html-slide 模板包",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = p.add_subparsers(dest="command")

    pm = sub.add_parser(
        "ppt-master",
        help="PPT Master 管线：规范 SVG → 原生 PPTX → 转 html-slide 模板包",
    )
    pm.add_argument("prompt", nargs="*", help="主题 / 风格描述")
    pm.add_argument("--mock", action="store_true", help="不调 LLM，写示意 SVG")
    pm.add_argument("--pages", type=int, default=7, help="页数，默认 7（3–12）")
    pm.add_argument("--count", type=int, default=1, help="生成包数，默认 1（上限 20）")
    pm.add_argument(
        "--style",
        default="dark-tech",
        help=(
            "视觉风格 id，或一段风格意图（配合 --ensure-style）。"
            "已有卡见 _catalog.json；重建：python -m webppt_agent styles-catalog"
        ),
    )
    pm.add_argument(
        "--ensure-style",
        action="store_true",
        help=(
            "风格不存在时按 style-skill 契约自动生成风格卡并写入 visual-styles/，"
            "近义风格则复用已有卡（不重复建卡）"
        ),
    )
    pm.add_argument(
        "--style-intent",
        default="",
        help="自然语言风格意图；优先于 --style。需配合 --ensure-style",
    )
    pm.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="html-slide 输出根（默认仓库 agent-output/）",
    )
    pm.add_argument(
        "--slide-concurrency",
        type=int,
        default=4,
        help="单包内 SVG 并行数，默认 4",
    )
    pm.add_argument(
        "--fast-preview",
        action="store_true",
        help="等价于 --quality-gate skip（跳过质检直接导出）；默认关闭",
    )
    pm.add_argument(
        "--quality-gate",
        choices=("soft", "strict", "skip"),
        default="soft",
        help=(
            "质检门禁：soft=失败仍 soft-pass 导出（默认）；"
            "strict=失败即停；skip=跳过质检直接导出"
        ),
    )
    pm.add_argument(
        "--svg-repair",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="门禁失败后执行 bounds/LLM 修复（默认开；--no-svg-repair 只检不修；skip 时无效）",
    )
    pm.add_argument(
        "--strip-unsupported",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "导出前剥离非法节点/属性（SMIL animate、HTML br、悬空 marker、"
            "text@dx、非法 clip-path；默认开）"
        ),
    )
    pm.add_argument(
        "--skip-image",
        action="store_true",
        help="跳过文生图（不写 <image>；等价 AGENT_SKIP_IMAGE=1）",
    )
    pm.add_argument(
        "--with-images",
        action="store_true",
        help="强制启用文生图（覆盖 AGENT_SKIP_IMAGE；需配置 IMAGE_API_KEY）",
    )
    pm.add_argument(
        "--palette-refine",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Plan 后对 palette 做对比度精修（colorspacious/WCAG）；"
            "默认跟 AGENT_PALETTE_REFINE（未设则关）"
        ),
    )
    pm.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：写入 JSON 报告",
    )

    vs = sub.add_parser(
        "visual-spec",
        help="为已有模板包生成 visual-spec.md（审批通过后补规范）",
    )
    vs.add_argument(
        "package",
        type=Path,
        help="模板包目录（含 template.json）",
    )
    vs.add_argument(
        "--mock",
        action="store_true",
        help="不调 LLM，写本地骨架",
    )

    sc = sub.add_parser(
        "styles-catalog",
        help="扫描 visual-styles/ 并重建 _catalog.json",
    )
    sc.add_argument(
        "--list",
        action="store_true",
        help="重建后打印 id 列表",
    )

    es = sub.add_parser(
        "ensure-style",
        help="解析风格意图：命中复用 / 缺失则按 style-skill 写卡并重建目录",
    )
    es.add_argument("intent", nargs="+", help="风格 id 或自然语言意图")
    es.add_argument(
        "--create",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="允许新建风格卡（默认开；--no-create 仅查重）",
    )
    es.add_argument("--mock", action="store_true", help="不调 LLM，写 mock 卡")
    es.add_argument(
        "--json",
        action="store_true",
        help="只打印一行 JSON 结果",
    )

    rx = sub.add_parser(
        "remix-template",
        help="套用已有模板：克隆包并只改 data-slot 文案/配图（保版式配色）",
    )
    rx.add_argument(
        "source",
        help="源模板 id 或目录（默认在 agent-output/ 下）",
    )
    rx.add_argument(
        "prompt",
        nargs="*",
        help="新内容要求（也可用 --prompt）",
    )
    rx.add_argument(
        "--prompt",
        dest="prompt_flag",
        default="",
        help="新内容要求（优先于位置参数）",
    )
    rx.add_argument("--mock", action="store_true", help="不调 LLM，示意改写")
    rx.add_argument(
        "--skip-image",
        action="store_true",
        help="保留原图，不重生图",
    )
    rx.add_argument(
        "--with-images",
        action="store_true",
        help="按新主题重生 image 槽位",
    )
    rx.add_argument(
        "--out-root",
        type=Path,
        default=None,
        help="输出根目录（默认 agent-output/）",
    )
    rx.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：写入 JSON 报告（数组，兼容 Admin）",
    )

    sub.add_parser("doctor", help="检查 LLM 配置是否可用")
    return p


def _cmd_visual_spec(args: argparse.Namespace) -> int:
    from webppt_agent.templates.visual_spec import generate_visual_spec

    package = args.package.expanduser().resolve()
    try:
        out = generate_visual_spec(package, mock=bool(args.mock))
    except Exception as e:
        print(f"visual-spec: FAIL — {e}", file=sys.stderr)
        return 1
    print(f"wrote: {out}")
    return 0


def _cmd_doctor() -> int:
    print(f"webppt-agent {__version__}")

    try:
        cfg = llm_config()
        print(f"LLM heavy BASE_URL: {cfg.base_url}")
        print(f"LLM heavy MODEL: {cfg.model}")
        print(f"LLM heavy KEYS: {len(cfg.api_keys)} key(s)")
    except Exception as e:
        print(f"LLM heavy: FAIL — {e}")
        return 1

    from webppt_agent.config import llm_light_config
    from webppt_agent.llm import make_client

    try:
        light = llm_light_config()
        same = (
            light.base_url == cfg.base_url
            and light.model == cfg.model
            and light.api_keys == cfg.api_keys
        )
        if same:
            print("LLM light: same as heavy (Plan)")
        else:
            print(f"LLM light BASE_URL: {light.base_url}")
            print(f"LLM light MODEL: {light.model}")
            print(f"LLM light KEYS: {len(light.api_keys)} key(s)")
    except Exception as e:
        print(f"LLM light: FAIL — {e}")
        return 1

    try:
        client = make_client(cfg)
        r = client.chat.completions.create(
            model=cfg.model,
            messages=[{"role": "user", "content": "只回复：ok"}],
            max_tokens=8,
        )
        text = (r.choices[0].message.content or "").strip()
        print(f"LLM heavy ping: OK ({text[:40]!r})")
    except Exception as e:
        print(f"LLM heavy ping: FAIL — {e}")
        return 1
    return 0


def _cmd_styles_catalog(args: argparse.Namespace) -> int:
    from webppt_agent.ppt_master.styles import load_catalog, rebuild_catalog

    path = rebuild_catalog()
    print(f"[ok] {path}")
    data = load_catalog()
    print(f"[ok] count={data.get('count')}")
    if args.list:
        for item in data.get("styles") or []:
            if isinstance(item, dict):
                print(
                    f"  {item.get('status', '?'):12} {item.get('id')}  "
                    f"[{item.get('group_zh')}]"
                )
    return 0


def _cmd_ppt_master(args: argparse.Namespace) -> int:
    from webppt_agent.ppt_master.pipeline import run_ppt_master_pipeline
    from webppt_agent.ppt_master.style_author import ensure_style
    from webppt_agent.ppt_master.styles import assert_valid_style_id, normalize_style_id

    prompt = " ".join(args.prompt).strip() if args.prompt else ""
    if not prompt:
        prompt = (
            "虚构 AI 产品发布会：冲击力封面、章节页、三栏能力、数据页、系统流转、收尾。"
            "视觉 dark-tech，禁止说明书式排版。"
        )
    intent = (getattr(args, "style_intent", None) or "").strip()
    style = (args.style or "dark-tech").strip()
    allow_create = bool(getattr(args, "ensure_style", False))
    log = lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True)
    mock = bool(args.mock) or is_mock()
    if intent:
        try:
            resolved = ensure_style(
                intent, allow_create=allow_create, mock=mock, log=log
            )
            style = str(resolved["id"])
            print(
                f"[style] resolved {style} created={resolved.get('created')} "
                f"reason={resolved.get('reason')}"
            )
        except Exception as e:
            print(f"[style] FAIL — {e}", file=sys.stderr)
            return 1
    elif allow_create:
        try:
            style = assert_valid_style_id(style)
        except ValueError:
            try:
                resolved = ensure_style(
                    style, allow_create=True, mock=mock, log=log
                )
                style = str(resolved["id"])
                print(
                    f"[style] resolved {style} created={resolved.get('created')}"
                )
            except Exception as e:
                print(f"[style] FAIL — {e}", file=sys.stderr)
                return 1
    else:
        try:
            style = assert_valid_style_id(style)
        except ValueError as e:
            print(f"[style] WARN {e}")
            style = normalize_style_id(style)
            print(f"[style] using {style!r}")
    skip_images: bool | None = None
    if bool(getattr(args, "skip_image", False)):
        skip_images = True
    elif bool(getattr(args, "with_images", False)):
        skip_images = False
    palette_refine = getattr(args, "palette_refine", None)
    rows = run_ppt_master_pipeline(
        prompt,
        count=max(1, int(args.count or 1)),
        pages=max(3, min(12, int(args.pages or 7))),
        visual_style=style,
        out_root=args.out_root,
        mock=mock,
        skip_images=skip_images,
        palette_refine=palette_refine,
        slide_concurrency=max(1, int(args.slide_concurrency or 4)),
        fast_preview=bool(args.fast_preview),
        svg_repair=bool(getattr(args, "svg_repair", True)),
        quality_gate=str(getattr(args, "quality_gate", None) or "soft"),
        strip_unsupported=bool(getattr(args, "strip_unsupported", True)),
        log=lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True),
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[report] {args.report}")
    ok = sum(1 for r in rows if r.get("ok"))
    fail = len(rows) - ok
    print(f"[summary] ok={ok} fail={fail}")
    return 0 if fail == 0 and ok > 0 else 1


def _cmd_ensure_style(args: argparse.Namespace) -> int:
    from webppt_agent.ppt_master.style_author import ensure_style

    intent = " ".join(args.intent).strip()
    if not intent:
        print("ensure-style: intent required", file=sys.stderr)
        return 2
    mock = bool(args.mock) or is_mock()
    try:
        out = ensure_style(
            intent,
            allow_create=bool(args.create),
            mock=mock,
            log=None
            if args.json
            else (lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True)),
        )
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            print(f"ensure-style: FAIL — {e}", file=sys.stderr)
        return 1
    payload = {"ok": True, **out}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(
            f"[ok] id={out.get('id')} created={out.get('created')} "
            f"reason={out.get('reason')} path={out.get('path')}"
        )
    return 0


def _cmd_remix_template(args: argparse.Namespace) -> int:
    from webppt_agent.templates.remix import run_remix

    prompt = (getattr(args, "prompt_flag", None) or "").strip()
    if not prompt:
        prompt = " ".join(getattr(args, "prompt", None) or []).strip()
    if not prompt:
        print("remix-template: prompt required", file=sys.stderr)
        return 2
    skip_images = True
    if bool(getattr(args, "with_images", False)):
        skip_images = False
    elif bool(getattr(args, "skip_image", False)):
        skip_images = True
    try:
        row = run_remix(
            str(args.source),
            prompt,
            out_root=args.out_root,
            mock=bool(args.mock) or is_mock(),
            skip_images=skip_images,
            log=lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True),
        )
    except Exception as e:
        print(f"[remix] FAIL — {e}", file=sys.stderr)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(
                    [{"ok": False, "error": str(e), "template_id": None}],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return 1
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps([row], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[report] {args.report}")
    print(f"[summary] ok=1 fail=0 id={row.get('template_id')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env()
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "visual-spec":
        return _cmd_visual_spec(args)
    if args.command == "styles-catalog":
        return _cmd_styles_catalog(args)
    if args.command == "ensure-style":
        return _cmd_ensure_style(args)
    if args.command == "remix-template":
        return _cmd_remix_template(args)
    if args.command == "ppt-master":
        return _cmd_ppt_master(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
