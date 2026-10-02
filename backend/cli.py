from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import is_mock, llm_config, load_env

__version__ = "0.3.0"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="webppt-backend",
        description="WebPPT 后端：API 服务与 PPT Master 生成管线",
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
            "已有卡见 _catalog.json；重建：webppt-backend styles-catalog"
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
        "--category",
        default="",
        help=(
            "模板类型覆盖（= 视觉风格 id，如 dark-tech）；"
            "留空则与 --style 相同"
        ),
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
        default=3,
        help="单包内 SVG 并行数，默认 3（上限见 AGENT_SLIDE_CONCURRENCY_MAX，默认 8）",
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
    rx.add_argument(
        "--status",
        choices=["pending", "approved"],
        default="pending",
        help="新模板状态（首页 remix 用 approved 以便直接进编辑器）",
    )
    rx.add_argument(
        "--ephemeral",
        action="store_true",
        help="标记为临时会话包（首页 remix：写 sessions/，不进模板库）",
    )

    rw = sub.add_parser(
        "rewrite-page",
        help="按问题原位重写模板某一页 HTML（可改文案/版式，保留 theme 与本地图）",
    )
    rw.add_argument(
        "package",
        help="模板 id 或目录（默认在 agent-output/ 下）",
    )
    rw.add_argument(
        "--file",
        default="",
        help="页面相对路径，如 slides/cover.html",
    )
    rw.add_argument(
        "--page-index",
        type=int,
        default=None,
        help="0-based 页码（与 --file 二选一）",
    )
    rw.add_argument(
        "--issue",
        required=True,
        help="本页问题描述",
    )
    rw.add_argument("--mock", action="store_true", help="不调 LLM，写注释标记")
    rw.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：写入 JSON 报告（数组）",
    )

    gp = sub.add_parser(
        "generate-page",
        help="按要求在模板包中新增一页 HTML（保留 theme 与本地图）",
    )
    gp.add_argument(
        "package",
        help="模板 id 或目录（默认在 agent-output/ 下）",
    )
    gp.add_argument(
        "--issue",
        required=True,
        help="新页内容要求",
    )
    gp.add_argument(
        "--after-file",
        default="",
        help="插入到该页之后（相对路径，如 slides/cover.html）",
    )
    gp.add_argument(
        "--after-page-index",
        type=int,
        default=None,
        help="插入到该 0-based 页码之后",
    )
    gp.add_argument(
        "--title-hint",
        default="",
        help="可选标题提示",
    )
    gp.add_argument("--mock", action="store_true", help="不调 LLM，写 mock 页")
    gp.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：写入 JSON 报告（数组）",
    )

    dp = sub.add_parser(
        "delete-page",
        help="从模板包删除一页 HTML（至少保留一页）",
    )
    dp.add_argument("package", help="模板 id 或目录（默认在 agent-output/ 或 workspace/）")
    dp.add_argument("--file", default="", help="页面相对路径，如 slides/cover.html")
    dp.add_argument(
        "--page-index",
        type=int,
        default=None,
        help="0-based 页码（与 --file 二选一）",
    )
    dp.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：写入 JSON 报告（数组）",
    )

    asst = sub.add_parser(
        "editor-assist",
        help="AI 帮写：规划并串行执行 modify / regenerate_image / add / delete",
    )
    asst.add_argument("package", help="模板 id 或目录（workspace / agent-output）")
    asst.add_argument("--issue", required=True, help="用户自然语言指令")
    asst.add_argument("--file", default="", help="当前页相对路径，如 slides/cover.html")
    asst.add_argument(
        "--page-index",
        type=int,
        default=None,
        help="当前页 0-based 页码（与 --file 二选一或同时）",
    )
    asst.add_argument("--mock", action="store_true", help="不调 LLM / 生图 API")
    asst.add_argument(
        "--target-json",
        type=Path,
        default=None,
        help="可选：画布选中元素 JSON 文件（selector / data-slot / imageSrc 等）",
    )
    asst.add_argument(
        "--report",
        type=Path,
        default=None,
        help="可选：写入 JSON 报告（数组）",
    )

    sub.add_parser("doctor", help="检查 LLM 配置是否可用")

    gs = sub.add_parser(
        "gallery-serve",
        help="启动 API（gallery + admin，默认 127.0.0.1:8787；同 serve）",
    )
    gs.add_argument("--host", default="127.0.0.1")
    gs.add_argument("--port", type=int, default=8787)

    sv = sub.add_parser(
        "serve",
        help="启动 WebPPT API（gallery + admin，默认 127.0.0.1:8787）",
    )
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8787)

    sub.add_parser(
        "gallery-sync",
        help="把 agent-output 里已上传模板写入 PostgreSQL",
    )
    gbc = sub.add_parser(
        "gallery-backfill-categories",
        help="为缺少/旧业务类型的模板按 visual_style 回填类型并双写 DB",
    )
    gbc.add_argument(
        "--force",
        action="store_true",
        help="覆盖已有 category（默认只补缺失与旧业务类）",
    )
    return p


def _cmd_visual_spec(args: argparse.Namespace) -> int:
    from templates.visual_spec import generate_visual_spec

    package = args.package.expanduser().resolve()
    try:
        out = generate_visual_spec(package, mock=bool(args.mock))
    except Exception as e:
        print(f"visual-spec: FAIL — {e}", file=sys.stderr)
        return 1
    print(f"wrote: {out}")
    return 0


def _cmd_doctor() -> int:
    print(f"webppt-backend {__version__}")

    try:
        cfg = llm_config()
        print(f"LLM heavy BASE_URL: {cfg.base_url}")
        print(f"LLM heavy MODEL: {cfg.model}")
        print(f"LLM heavy KEYS: {len(cfg.api_keys)} key(s)")
    except Exception as e:
        print(f"LLM heavy: FAIL — {e}")
        return 1

    from config import llm_light_config
    from llm import make_client

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
    from ppt_master.styles import load_catalog, rebuild_catalog

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
    from ppt_master.pipeline import run_ppt_master_pipeline
    from ppt_master.style_author import ensure_style
    from ppt_master.styles import assert_valid_style_id, normalize_style_id

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
    category = str(getattr(args, "category", "") or "").strip().lower()
    if category and category != "auto":
        from templates.categories import normalize_category

        normalized = normalize_category(category)
        if not normalized:
            print(
                f"[category] FAIL — 无效类型 {category!r}",
                file=sys.stderr,
            )
            return 1
        import os

        os.environ["AGENT_TEMPLATE_CATEGORY"] = normalized
        print(f"[category] override={normalized}")
    rows = run_ppt_master_pipeline(
        prompt,
        count=max(1, int(args.count or 1)),
        pages=max(3, min(12, int(args.pages or 7))),
        visual_style=style,
        out_root=args.out_root,
        mock=mock,
        skip_images=skip_images,
        palette_refine=palette_refine,
        slide_concurrency=max(1, int(args.slide_concurrency or 3)),
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
    from ppt_master.style_author import ensure_style

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
    from templates.remix import run_remix

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
            status=str(getattr(args, "status", None) or "pending"),
            ephemeral=bool(getattr(args, "ephemeral", False)),
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


def _cmd_rewrite_page(args: argparse.Namespace) -> int:
    from templates.page_rewrite import run_page_rewrite
    from admin.fsutil import template_dir

    package = str(args.package).strip()
    root = Path(package).expanduser()
    if not root.is_dir():
        root = template_dir(package)
    issue = str(args.issue or "").strip()
    try:
        row = run_page_rewrite(
            root,
            slide_file=(str(args.file).strip() or None),
            page_index=getattr(args, "page_index", None),
            issue=issue,
            mock=bool(args.mock) or is_mock(),
            log=lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True),
        )
    except Exception as e:
        print(f"[rewrite-page] FAIL — {e}", file=sys.stderr)
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
    print(f"[summary] ok=1 fail=0 id={row.get('template_id')} file={row.get('file')}")
    return 0


def _cmd_generate_page(args: argparse.Namespace) -> int:
    from templates.page_generate import run_page_generate
    from ppt_master.paths import repo_root

    package = str(args.package).strip()
    root = Path(package).expanduser()
    if not root.is_dir():
        from admin.fsutil import template_dir

        root = template_dir(package)
    issue = str(args.issue or "").strip()
    try:
        row = run_page_generate(
            root,
            issue=issue,
            after_file=(str(args.after_file).strip() or None),
            after_page_index=getattr(args, "after_page_index", None),
            title_hint=(str(args.title_hint).strip() or None),
            mock=bool(args.mock) or is_mock(),
            log=lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True),
        )
    except Exception as e:
        print(f"[generate-page] FAIL — {e}", file=sys.stderr)
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
    print(
        f"[summary] ok=1 fail=0 id={row.get('template_id')} "
        f"file={row.get('file')} insertAt={row.get('insertAt')}"
    )
    return 0


def _cmd_delete_page(args: argparse.Namespace) -> int:
    from templates.page_delete import run_page_delete
    from admin.fsutil import template_dir

    package = str(args.package).strip()
    root = Path(package).expanduser()
    if not root.is_dir():
        root = template_dir(package)
    try:
        row = run_page_delete(
            root,
            slide_file=(str(args.file).strip() or None),
            page_index=getattr(args, "page_index", None),
            log=lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True),
        )
    except Exception as e:
        print(f"[delete-page] FAIL — {e}", file=sys.stderr)
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
    print(
        f"[summary] ok=1 fail=0 id={row.get('template_id')} "
        f"file={row.get('file')} activateFile={row.get('activateFile')}"
    )
    return 0


def _cmd_editor_assist(args: argparse.Namespace) -> int:
    from templates.editor_execute import run_editor_assist
    from templates.element_target import normalize_element_target
    from admin.fsutil import template_dir

    package = str(args.package).strip()
    root = Path(package).expanduser()
    if not root.is_dir():
        root = template_dir(package)
    issue = str(args.issue or "").strip()
    target = None
    target_path = getattr(args, "target_json", None)
    if target_path:
        try:
            raw = Path(target_path).read_text(encoding="utf-8")
            target = normalize_element_target(json.loads(raw))
        except Exception as e:
            print(f"[editor-assist] FAIL — 无法读取 --target-json：{e}", file=sys.stderr)
            return 1
    try:
        row = run_editor_assist(
            root,
            issue=issue,
            slide_file=(str(args.file).strip() or None),
            page_index=getattr(args, "page_index", None),
            mock=bool(args.mock) or is_mock(),
            target_element=target,
            log=lambda s: print(s, end="" if s.endswith("\n") else "\n", flush=True),
        )
    except Exception as e:
        print(f"[editor-assist] FAIL — {e}", file=sys.stderr)
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
    status = "ok" if row.get("ok") else "partial"
    print(
        f"[summary] {status} id={row.get('template_id')} "
        f"intent={row.get('intent')} file={row.get('file')} "
        f"images={row.get('regeneratedImages')}"
    )
    return 0 if row.get("ok") else 1


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
    if args.command == "rewrite-page":
        return _cmd_rewrite_page(args)
    if args.command == "generate-page":
        return _cmd_generate_page(args)
    if args.command == "delete-page":
        return _cmd_delete_page(args)
    if args.command == "editor-assist":
        return _cmd_editor_assist(args)
    if args.command == "ppt-master":
        return _cmd_ppt_master(args)
    if args.command == "gallery-serve":
        return _cmd_gallery_serve(args)
    if args.command == "serve":
        return _cmd_gallery_serve(args)
    if args.command == "gallery-sync":
        return _cmd_gallery_sync()
    if args.command == "gallery-backfill-categories":
        return _cmd_gallery_backfill_categories(args)

    parser.print_help()
    return 2


def _cmd_gallery_sync() -> int:
    from gallery.db import connect, sync_from_disk

    try:
        with connect() as conn:
            result = sync_from_disk(conn)
    except Exception as e:
        print(f"gallery-sync: FAIL — {e}", file=sys.stderr)
        return 1
    print(f"gallery-sync: upserted={result['upserted']}")
    return 0


def _cmd_gallery_backfill_categories(args: argparse.Namespace) -> int:
    from admin.store import backfill_categories

    try:
        result = backfill_categories(force=bool(getattr(args, "force", False)))
    except Exception as e:
        print(f"gallery-backfill-categories: FAIL — {e}", file=sys.stderr)
        return 1
    print(
        "gallery-backfill-categories: "
        f"updated={result['updated']} skipped={result['skipped']}"
    )
    return 0


def _cmd_gallery_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "serve: 缺少依赖。请在 backend/ 执行 pip install -e '.[api]'",
            file=sys.stderr,
        )
        return 1
    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        factory=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
