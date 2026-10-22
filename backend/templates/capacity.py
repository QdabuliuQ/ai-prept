"""Compile and validate a reusable capacity contract for template packs.

The contract is deliberately structural: geometry, slot identity, row/column,
field order and safe character budgets. Copy is kept only as a short sample so a
generated pack can reuse the same contract after its source copy is rewritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPACITY_FILE = "capacity.json"
CAPACITY_SCHEMA_VERSION = "1.1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_field_key(value: str, used: dict[str, int]) -> str:
    key = re.sub(r"[^a-z0-9_]+", "_", (value or "text").lower()).strip("_")
    key = key or "text"
    used[key] = used.get(key, 0) + 1
    return key if used[key] == 1 else f"{key}_{used[key]}"


def _structural_html(raw: str) -> str:
    """Drop text runs while keeping every tag and style attribute.

    Capacity depends on geometry and typography, not the current copy. Keeping tags
    and attributes lets us invalidate the contract when a page or CSS box changes,
    while normal remix copy changes leave the fingerprint stable.
    """
    return re.sub(r">([^<>]+)<", "><", raw)


def package_fingerprint(pack_dir: str | Path) -> str:
    root = Path(pack_dir)
    try:
        meta = json.loads((root / "template.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        meta = {}
    digest = hashlib.sha256()
    digest.update(CAPACITY_SCHEMA_VERSION.encode())
    slides = meta.get("slides") if isinstance(meta.get("slides"), list) else []
    for slide in slides:
        rel = str((slide or {}).get("file") or "").strip() if isinstance(slide, dict) else ""
        if not rel:
            continue
        path = root / rel
        digest.update(rel.encode())
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            digest.update(b"<missing>")
            continue
        digest.update(_structural_html(raw).encode("utf-8"))
    theme = root / "theme.css"
    if theme.is_file():
        digest.update(b"theme.css\0")
        digest.update(theme.read_bytes())
    return digest.hexdigest()


def _field_lines(slot: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [str(x or "text") for x in (slot.get("fields") or [])]
    budgets = [int(x or 0) for x in (slot.get("line_budgets") or [])]
    fallback = int(slot.get("line_chars") or slot.get("max_chars") or 1)
    line_count = int(slot.get("line_count") or max(len(fields), len(budgets), 1))
    samples = str(slot.get("current") or "").splitlines()
    used: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for i in range(line_count):
        field = _clean_field_key(fields[i] if i < len(fields) else "text", used)
        out.append(
            {
                "field": field,
                "sample": (samples[i] if i < len(samples) else "")[:80],
                "max_chars": max(1, budgets[i] if i < len(budgets) else fallback),
            }
        )
    return out


def _contract_slot(slot: dict[str, Any], order: int) -> dict[str, Any]:
    width = round(float(slot.get("box_width_px") or 0), 1)
    height = round(float(slot.get("box_height_px") or 0), 1)
    out: dict[str, Any] = {
        "slot": str(slot.get("slot") or ""),
        "type": str(slot.get("type") or "text"),
        "role": str(slot.get("role") or ""),
        "order": order,
        "group": "row" if slot.get("row") else "standalone",
        "row": slot.get("row"),
        "col": slot.get("col"),
        "bbox": {"width": width, "height": height},
    }
    if out["type"] == "text":
        out["capacity"] = {
            "max_chars": int(slot.get("max_chars") or 1),
            "lines": _field_lines(slot),
            "nowrap": bool(slot.get("nowrap")),
        }
    elif out["type"] == "image":
        out["capacity"] = {"prompt_chars": int(slot.get("max_chars") or 120)}
    return out


def _contract_issues(slots: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for slot in slots:
        file = str(slot.get("file") or "")
        slot_id = str(slot.get("slot") or "")
        key = (file, slot_id)
        if not slot_id:
            issues.append({"file": file, "slot": "", "code": "missing_slot_id"})
            continue
        if key in seen:
            issues.append({"file": file, "slot": slot_id, "code": "duplicate_slot"})
        seen.add(key)
        if slot.get("type") == "text":
            if float(slot.get("box_width_px") or 0) <= 0:
                issues.append({"file": file, "slot": slot_id, "code": "missing_width"})
            if float(slot.get("box_height_px") or 0) <= 0:
                issues.append({"file": file, "slot": slot_id, "code": "missing_height"})
            if not slot.get("fields"):
                issues.append(
                    {"file": file, "slot": slot_id, "code": "missing_field_order"}
                )
    return issues


def build_capacity_contract(
    pack_dir: str | Path,
    *,
    repair_structure: bool = True,
    render_baseline: bool = False,
) -> dict[str, Any]:
    """Build (and atomically write) ``capacity.json`` for one template pack."""
    from templates.remix import inventory_package_slots
    from templates.slot_tree import split_package_slots

    root = Path(pack_dir).resolve()
    if repair_structure:
        try:
            from templates.slot_ensure import ensure_package_orphan_slots

            ensure_package_orphan_slots(root)
        except Exception:  # noqa: BLE001 - structural repair is best effort
            pass
        try:
            split_package_slots(root)
        except Exception:  # noqa: BLE001
            pass

    slots = inventory_package_slots(root)
    pages: dict[str, dict[str, Any]] = {}
    for slot in slots:
        file = str(slot.get("file") or "")
        page = pages.setdefault(file, {"file": file, "slots": []})
        page["slots"].append(_contract_slot(slot, len(page["slots"])))

    issues = _contract_issues(slots)
    if not slots:
        issues.append({"file": "", "slot": "", "code": "no_dynamic_slots"})
    has_text = any(s.get("type") == "text" and s.get("box_width_px") for s in slots)
    if slots and not has_text:
        issues.append({"file": "", "slot": "", "code": "no_text_slots"})
    fatal_codes = {
        "no_dynamic_slots",
        "no_text_slots",
        "missing_slot_id",
        "duplicate_slot",
        "missing_width",
        "missing_height",
    }
    fatal = any(issue["code"] in fatal_codes for issue in issues)
    baseline: dict[str, Any] | None = None
    if render_baseline:
        try:
            from templates.render_check import check_package_render

            baseline = check_package_render(root)
        except Exception as exc:  # noqa: BLE001 - browser is optional at compile time
            baseline = {"engine": "none", "issues": [], "error": str(exc)}

    contract: dict[str, Any] = {
        "schema_version": CAPACITY_SCHEMA_VERSION,
        "source_fingerprint": package_fingerprint(root),
        "compiled_at": _now(),
        "status": "review_required" if fatal else "ready",
        "summary": {
            "pages": len(pages),
            "slots": len(slots),
            "text_slots": sum(s.get("type") == "text" for s in slots),
            "image_slots": sum(s.get("type") == "image" for s in slots),
            "rows": len({(s.get("file"), s.get("row")) for s in slots if s.get("row")}),
            "issues": len(issues),
        },
        "issues": issues,
        "pages": list(pages.values()),
    }
    if baseline is not None:
        contract["baseline_render"] = {
            "engine": baseline.get("engine"),
            "stop_reason": baseline.get("error"),
            "issues": (baseline.get("issues") or [])[:80],
        }

    target = root / CAPACITY_FILE
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)
    return contract


def capacity_status(pack_dir: str | Path) -> dict[str, Any]:
    """Return a cheap, read-only contract status for Admin and use gates."""
    root = Path(pack_dir)
    path = root / CAPACITY_FILE
    if not path.is_file():
        return {
            "hasCapacity": False,
            "capacityStatus": "missing",
            "capacitySlots": 0,
            "capacityIssues": 0,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "hasCapacity": True,
            "capacityStatus": "invalid",
            "capacitySlots": 0,
            "capacityIssues": 1,
        }
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    stale = (
        data.get("schema_version") != CAPACITY_SCHEMA_VERSION
        or data.get("source_fingerprint") != package_fingerprint(root)
    )
    status = "stale" if stale else str(data.get("status") or "invalid")
    if status not in {"ready", "review_required", "stale"}:
        status = "invalid"
    return {
        "hasCapacity": True,
        "capacityStatus": status,
        "capacitySlots": int(summary.get("slots") or 0),
        "capacityIssues": int(summary.get("issues") or 0),
        "capacityCompiledAt": data.get("compiled_at"),
    }


def ensure_capacity_contract(
    pack_dir: str | Path,
    *,
    rebuild_stale: bool = True,
    render_baseline: bool = False,
) -> dict[str, Any]:
    """Load a fresh contract, rebuilding missing/stale structural data if allowed."""
    root = Path(pack_dir)
    status = capacity_status(root)
    if status["capacityStatus"] == "ready":
        try:
            return json.loads((root / CAPACITY_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if not rebuild_stale:
        return status
    return build_capacity_contract(root, render_baseline=render_baseline)


def capacity_for_slots(
    pack_dir: str | Path,
    slots: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index contract slots by ``(file, slot)`` and ignore stale contracts."""
    root = Path(pack_dir)
    status = capacity_status(root)
    if status["capacityStatus"] != "ready":
        return {}
    try:
        data = json.loads((root / CAPACITY_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    wanted = {(str(s.get("file") or ""), str(s.get("slot") or "")) for s in slots}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for page in data.get("pages") or []:
        file = str((page or {}).get("file") or "")
        for item in (page or {}).get("slots") or []:
            key = (file, str((item or {}).get("slot") or ""))
            if key in wanted:
                out[key] = item
    return out
