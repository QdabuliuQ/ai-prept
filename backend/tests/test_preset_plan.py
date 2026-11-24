"""``preset_plan`` 注入点：agent 的规划交给流水线，但**验收权不放给调用方**。

这是 S1 阶段的核心机制：
- agent 只接管"规划"这一步；
- 样式卡、SVG 生成、质检、导出 100% 仍是 PPT Master 的流水线；
- 传进来的 plan 仍要过 ``_validate_plan``——不合格就抛错，不会因为
  "外部规划器说它合格"而放行。

测试用 ``tmp_path`` 里生成的最小 stub skill，不依赖真实 PPT Master ZIP。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

STUB_SCRIPTS = {
    "project_manager.py": """
        import pathlib, sys, datetime
        name = sys.argv[2]
        root = pathlib.Path.cwd() / "projects"
        root.mkdir(parents=True, exist_ok=True)
        d = root / f"{name}_{datetime.date.today().strftime('%Y%m%d')}"
        for sub in ("svg_output", "images", "validation"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        print(f"[stub] created {d}")
    """,
    "svg_quality_checker.py": """
        import json, pathlib, sys
        project = pathlib.Path(sys.argv[1])
        page = sys.argv[sys.argv.index("--page") + 1] if "--page" in sys.argv else None
        out = project / "validation" / (
            "svg_quality_page_report.json" if page else "svg_quality_report.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        files = [
            {"file": p.name, "errors": []}
            for p in sorted((project / "svg_output").glob("*.svg"))
            if not page or p.name == page
        ]
        out.write_text(json.dumps({"passed": True, "files": files}))
        sys.exit(0)
    """,
    "svg_to_pptx.py": """
        import pathlib, sys
        out = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"PK\\x03\\x04stub")
        print(f"[stub] wrote {out}")
    """,
}

CATALOG = {
    "count": 1,
    "schema_version": "1.0",
    "styles": [
        {
            "id": "dark-tech",
            "label_zh": "暗色科技",
            "status": "curated",
            "group_zh": "企业 / 产品",
            "family": "corporate-product",
        }
    ],
}

CARD = """# 暗色科技

用色纪律：深色哑光底，单一高饱和强调色。
造型语言：几何切割、色带、大字号压阵。
"""


@pytest.fixture()
def stub_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """最小 PPT Master skill：足以让流水线跑通结构，不产生真 PPTX。"""
    root = tmp_path / "ppt-master"
    skill = root / "skills" / "ppt-master"
    (skill / "scripts").mkdir(parents=True)
    styles = skill / "references" / "visual-styles"
    styles.mkdir(parents=True)

    (skill / "SKILL.md").write_text("# stub\n", encoding="utf-8")
    for name, body in STUB_SCRIPTS.items():
        (skill / "scripts" / name).write_text(
            textwrap.dedent(body).strip() + "\n", encoding="utf-8"
        )
    (styles / "_catalog.json").write_text(
        json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8"
    )
    (styles / "dark-tech.md").write_text(CARD, encoding="utf-8")

    monkeypatch.setenv("PPT_MASTER_ROOT", str(root))
    monkeypatch.setenv("AGENT_MOCK", "1")
    return root


def _plan(pages: int = 3) -> dict:
    slides = [
        {
            "file": "01_cover.svg",
            "role": "cover",
            "title": "发布会",
            "core_message": "开场",
            "geometry": "满版暗场",
            "visual_hook": "光带",
            "layout_regions": [
                {
                    "id": "title",
                    "role": "page-title",
                    "bounds": [72, 56, 1136, 96],
                    "padding": [12, 16, 12, 16],
                    "clearance": 12,
                }
            ],
        },
        {
            "file": "02_content.svg",
            "role": "content",
            "title": "能力",
            "core_message": "三点",
            "geometry": "双栏",
            "visual_hook": "大数字",
            "layout_regions": [
                {
                    "id": "body",
                    "role": "body",
                    "bounds": [72, 176, 1136, 448],
                    "padding": [16, 16, 16, 16],
                    "clearance": 16,
                }
            ],
        },
        {
            "file": "03_ending.svg",
            "role": "ending",
            "title": "结束",
            "core_message": "收尾",
            "geometry": "横向",
            "visual_hook": "连线",
            "layout_regions": [
                {
                    "id": "body",
                    "role": "body",
                    "bounds": [72, 176, 1136, 448],
                    "padding": [16, 16, 16, 16],
                    "clearance": 16,
                }
            ],
        },
    ]
    return {
        "template_id": "星河智能产品发布会",
        "label_zh": "星河智能产品发布会",
        "visual_style": "dark-tech",
        "palette": {
            "bg": "#0A0E14",
            "panel": "#141A22",
            "text": "#F2F5F8",
            "muted": "#8A96A3",
            "accent": "#4DA3FF",
            "accent2": "#FF7A45",
        },
        "slides": slides[:pages],
    }


def _run(stub_skill: Path, tmp_path: Path, plan: dict | None, **over):
    from ppt_master.pipeline import run_one_package

    kwargs = dict(
        pages=3,
        visual_style="dark-tech",
        mock=True,
        skip_images=True,
        out_root=tmp_path / "out",
        preset_plan=plan,
        svg_repair=False,
        quality_gate="skip",
        log=None,
    )
    kwargs.update(over)
    return run_one_package("AI 产品发布会", **kwargs)


def test_preset_plan_is_accepted_and_used(stub_skill: Path, tmp_path: Path) -> None:
    """正常路径：外部 plan 被采纳，跳过内部 best-of-N 采样。"""
    row = _run(stub_skill, tmp_path, _plan())
    assert row.get("ok") is True, row
    assert row.get("template_id")
    # 落盘产物存在（stub 只写占位 pptx，但包目录应生成）
    assert Path(row["output_dir"]).is_dir()


def test_preset_plan_still_validated(stub_skill: Path, tmp_path: Path) -> None:
    """验收权不放给调用方：不合格的 preset_plan 必须抛错，不能放行。"""
    bad = _plan()
    bad["slides"] = bad["slides"][:2]  # 页数不匹配
    with pytest.raises(RuntimeError, match="页数"):
        _run(stub_skill, tmp_path, bad)


def test_preset_plan_rejects_region_outside_safe_area(
    stub_skill: Path, tmp_path: Path
) -> None:
    bad = _plan()
    bad["slides"][0]["layout_regions"][0]["bounds"] = [0, 0, 200, 100]
    with pytest.raises(RuntimeError, match="安全区"):
        _run(stub_skill, tmp_path, bad)


def test_preset_plan_rejects_unhealable_structure(
    stub_skill: Path, tmp_path: Path
) -> None:
    """机械修复不了的错误必须抛错（role 会被自动别名化，改用缺字段验证）。"""
    bad = _plan()
    bad["slides"][0]["core_message"] = ""
    with pytest.raises(RuntimeError, match="core_message"):
        _run(stub_skill, tmp_path, bad)


def test_preset_plan_heals_role_alias(stub_skill: Path, tmp_path: Path) -> None:
    """``closing`` 这类别名是机械可修的，应被正常化为 ``ending`` 而不是报错。"""
    plan = _plan()
    plan["slides"][2]["role"] = "closing"
    row = _run(stub_skill, tmp_path, plan)
    assert row.get("ok") is True, row


def test_without_preset_plan_uses_internal_planner(stub_skill: Path, tmp_path: Path) -> None:
    """不传 preset_plan 时行为与历史一致（内部 mock 规划器）。"""
    row = _run(stub_skill, tmp_path, None)
    assert row.get("ok") is True, row


def test_preset_plan_wins_over_internal_planner(
    stub_skill: Path, tmp_path: Path
) -> None:
    """传入的 plan 决定最终 template_id，而不是内部规划器生成的。"""
    plan = _plan()
    plan["template_id"] = "外部规划的名字"
    plan["label_zh"] = "外部规划的名字"
    row = _run(stub_skill, tmp_path, plan)
    assert row.get("ok") is True, row
    meta = json.loads((Path(row["output_dir"]) / "template.json").read_text("utf-8"))
    # 包名来自 preset_plan 的 label，而不是 mock 规划器的默认名
    assert "外部规划" in json.dumps(meta, ensure_ascii=False)


def test_repair_normalizes_region_bounds_and_padding():
    """LLM 常把 bounds 写成对象、padding 写成标量：repair 要能归一后通过校验。"""
    from ppt_master.pipeline import _validate_plan, repair_plan_layout

    plan = {
        "slides": [
            {
                "file": "01-cover.svg",
                "role": "cover",
                "title": "封面",
                "core_message": "一句话",
                "layout_regions": [
                    {
                        "id": "kicker",
                        "role": "kicker",
                        "bounds": {"x": 80, "y": 110, "w": 380, "h": 30},
                        "padding": 0,
                        "clearance": 28,
                    },
                    {
                        "id": "title",
                        "role": "headline",
                        "bounds": [80, 168, 700, 170],
                        "padding": [8, 8, 8, 8],
                        "clearance": 36,
                    },
                ],
            }
        ]
    }
    # 原始形状过不了校验，报错信息要点明实际收到的形状
    try:
        _validate_plan(plan, 1)
    except RuntimeError as exc:
        assert "bounds=对象" in str(exc)
        assert "padding=单个数字" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应当校验失败")

    repair_plan_layout(plan)
    _validate_plan(plan, 1)
    region = plan["slides"][0]["layout_regions"][0]
    assert region["bounds"] == [80.0, 110.0, 380.0, 40.0]
    assert region["padding"] == [0.0, 0.0, 0.0, 0.0]
