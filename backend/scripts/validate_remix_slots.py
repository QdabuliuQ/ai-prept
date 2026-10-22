"""End-to-end validation of slot splitting + fit + render check.

Runs the real remix pipeline against zBXOXIIhMjD1 with a *hand-written* plan that
mimics both a well-behaved model and the pathological case from the bug report
(model writes N lines per row slot, row has fewer leaves). No LLM call, so this is
deterministic and runnable offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from templates import remix as remix_mod  # noqa: E402
from templates.remix import inventory_package_slots, run_remix  # noqa: E402
from templates.render_check import check_package_render  # noqa: E402

SOURCE = "zBXOXIIhMjD1"
OUT = ROOT.parent / ".tmp-e2e"

# Fire-safety copy in the same rhythm as the source template (「共识清单 · 六件事」).
ROWS = [
    ("教室火源排查", "查插排、充电器与多媒体机柜，每周一次", "责任：安全委员", "节点：2026年9月"),
    ("宿舍用电清零", "离寝断插排、拔充电器，违规电器集中登记", "责任：寝室长", "节点：2026年10月"),
    ("报警点位置清", "说清楼栋、楼层与着火物，先拨119再报班主任", "责任：班长", "节点：2026年10月"),
    ("低姿撤离演练", "捂鼻低姿沿疏散通道靠右下行，不乘电梯", "责任：体育委员", "节点：2026年11月"),
    ("灭火器实操", "提拔握压，站上风口对准根部，两人一组", "责任：安全员", "节点：2026年12月"),
    ("值日岗位轮换", "报警、断电、清点、引导四岗每周轮换交接", "责任：班主任", "节点：2027年1月"),
]

FILLER = {
    "title": "校园消防六件事",
    "eyebrow": "值日分工 · 编号 01-06",
}


def build_plan(slots):
    """Produce per-file texts: realistic copy + one deliberately overlong slot."""
    texts: dict[str, dict[str, str]] = {}
    texts_by_file: dict[str, list[dict]] = {}
    for slot in slots:
        if slot.get("type") != "text":
            continue
        texts_by_file.setdefault(slot["file"], []).append(slot)

    for file, file_slots in texts_by_file.items():
        target: dict[str, str] = {}
        row_slots = [s for s in file_slots if s["slot"].startswith("body-3-")]
        pairs = len(row_slots) // 2
        for i, s in enumerate(row_slots):
            if pairs == 0:
                continue
            row = i // 2
            title, desc, owner, when = ROWS[row % len(ROWS)]
            if i % 2 == 0:
                target[s["slot"]] = f"{title}\n{desc}"
            else:
                target[s["slot"]] = f"{owner}\n{when}"
        for s in file_slots:
            if s["slot"] in target:
                continue
            role = (s.get("role") or "").lower()
            if role in {"page-title", "cover-title", "section-title", "heading"}:
                target[s["slot"]] = FILLER["title"]
            elif role == "meta":
                target[s["slot"]] = "疏散演练 · 消防值日"
            else:
                target[s["slot"]] = "发现火情先报警，再说清楼栋与楼层。"
        # Pathological: a 40-char line into a 12-char leaf column.
        if "body-3-2" in target:
            target["body-3-2"] = (
                "责任：学校安全办公室与年级组联合值守\n节点：2026年12月至2027年6月"
            )
        texts[file] = target
    return {"label_zh": "校园消防值日分工", "description_zh": "班级消防六件事与值日分工",
            "texts": texts, "images": {}}


def main() -> int:
    original = remix_mod._plan_content

    captured: dict = {}

    def fake_plan(**kwargs):
        slots = kwargs["slots"]
        if not captured:
            captured["slot_count"] = len(slots)
        return build_plan(slots)

    remix_mod._plan_content = fake_plan  # type: ignore[assignment]
    try:
        logs: list[str] = []
        row = run_remix(
            SOURCE,
            "初中班级消防安全宣讲：教室宿舍火源排查、报警撤离与班级值日分工",
            out_root=OUT,
            mock=False,
            skip_images=True,
            render_check=True,
            log=lambda m: (logs.append(m), print(m, end="")) and None,
        )
    finally:
        remix_mod._plan_content = original  # type: ignore[assignment]

    dest = Path(row["output_dir"])
    print(f"\n[out] {dest}")
    print(f"[out] text_slots={row['text_slots']} applied={row['text_applied']} "
          f"fit_warnings={row['fit_warnings']}")

    slots = inventory_package_slots(dest)
    print(f"[out] leaf text slots after split = {sum(1 for s in slots if s['type'] == 'text')}")

    probe = check_package_render(dest)
    print(f"[render] engine={probe['engine']} issues={len(probe['issues'])}")
    for item in probe["issues"][:10]:
        print("   ", item)
    return 0 if not probe["issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
