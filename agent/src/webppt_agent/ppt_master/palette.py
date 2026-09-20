"""Algorithmic palette refine: contrast gate + perceptual tweaks.

Uses colorspacious (JCh) when available; falls back to sRGB luminance nudges.
Does not invent a new aesthetic — only completes missing slots and lifts
failing text/muted contrast against bg.
"""

from __future__ import annotations

import os
import re
from typing import Any

_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")

# WCAG AA-ish targets for slide text
_MIN_TEXT_BG = 4.5
_MIN_MUTED_BG = 3.0
_MIN_ACCENT_BG = 2.5

_PALETTE_KEYS = ("bg", "panel", "text", "muted", "accent", "accent2")


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def palette_refine_enabled(explicit: bool | None = None) -> bool:
    """explicit wins; else AGENT_PALETTE_REFINE (default off)."""
    if explicit is not None:
        return bool(explicit)
    return _truthy("AGENT_PALETTE_REFINE", default=False)


def parse_hex(raw: Any) -> tuple[int, int, int] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = "#" + text
    if not _HEX_RE.match(text):
        return None
    h = text[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(rgb: tuple[float, float, float] | tuple[int, int, int]) -> str:
    r, g, b = rgb
    if max(r, g, b) <= 1.0 and isinstance(r, float):
        ri, gi, bi = int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    else:
        ri, gi, bi = int(round(r)), int(round(g)), int(round(b))
    ri = max(0, min(255, ri))
    gi = max(0, min(255, gi))
    bi = max(0, min(255, bi))
    return f"#{ri:02X}{gi:02X}{bi:02X}"


def _srgb01(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _srgb01(rgb)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def is_dark_field(bg: tuple[int, int, int]) -> bool:
    return relative_luminance(bg) < 0.45


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _nudge_lightness(
    rgb: tuple[int, int, int],
    *,
    toward_light: bool,
    step: float = 0.08,
) -> tuple[int, int, int]:
    """Move color lighter/darker in JCh when possible, else sRGB."""
    try:
        import numpy as np
        from colorspacious import cspace_convert

        arr = np.array(_srgb01(rgb), dtype=float)
        jch = cspace_convert(arr, "sRGB1", "JCh")
        # J is 0–100 lightness
        delta = 8.0 if toward_light else -8.0
        jch = np.array(jch, dtype=float)
        jch[0] = float(np.clip(jch[0] + delta * (step / 0.08), 2.0, 98.0))
        out = cspace_convert(jch, "JCh", "sRGB1")
        out = np.clip(out, 0.0, 1.0)
        return (
            int(round(float(out[0]) * 255)),
            int(round(float(out[1]) * 255)),
            int(round(float(out[2]) * 255)),
        )
    except Exception:
        r, g, b = _srgb01(rgb)
        if toward_light:
            r, g, b = (
                _clamp01(r + (1 - r) * step),
                _clamp01(g + (1 - g) * step),
                _clamp01(b + (1 - b) * step),
            )
        else:
            r, g, b = (
                _clamp01(r * (1 - step)),
                _clamp01(g * (1 - step)),
                _clamp01(b * (1 - step)),
            )
        return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def _mix(
    a: tuple[int, int, int],
    b: tuple[int, int, int],
    t: float,
) -> tuple[int, int, int]:
    t = _clamp01(t)
    return (
        int(round(a[0] * (1 - t) + b[0] * t)),
        int(round(a[1] * (1 - t) + b[1] * t)),
        int(round(a[2] * (1 - t) + b[2] * t)),
    )


def _ensure_contrast(
    fg: tuple[int, int, int],
    bg: tuple[int, int, int],
    *,
    min_ratio: float,
    prefer_light_text: bool,
) -> tuple[tuple[int, int, int], list[str]]:
    notes: list[str] = []
    cur = fg
    ratio = contrast_ratio(cur, bg)
    if ratio >= min_ratio:
        return cur, notes
    for _ in range(14):
        cur = _nudge_lightness(cur, toward_light=prefer_light_text, step=0.1)
        ratio = contrast_ratio(cur, bg)
        if ratio >= min_ratio:
            notes.append(f"contrast→{ratio:.1f}")
            return cur, notes
    # last resort: near-white / near-black
    fallback = (245, 247, 250) if prefer_light_text else (18, 20, 28)
    notes.append(f"fallback fg contrast={contrast_ratio(fallback, bg):.1f}")
    return fallback, notes


def _derive_missing(
    slots: dict[str, tuple[int, int, int]],
) -> dict[str, tuple[int, int, int]]:
    out = dict(slots)
    bg = out.get("bg") or (12, 14, 22)
    out.setdefault("bg", bg)
    dark = is_dark_field(bg)
    if "text" not in out:
        out["text"] = (244, 247, 255) if dark else (22, 24, 32)
    if "muted" not in out:
        out["muted"] = _mix(out["text"], bg, 0.45)
    if "panel" not in out:
        out["panel"] = _nudge_lightness(bg, toward_light=not dark, step=0.12)
    if "accent" not in out:
        # cool accent shifted from text hue via mix with a default
        seed = (61, 220, 255) if dark else (30, 100, 200)
        out["accent"] = _mix(seed, out["text"], 0.25)
    if "accent2" not in out:
        out["accent2"] = _mix(out["accent"], out.get("muted", out["text"]), 0.35)
    return out


def refine_palette(
    palette: dict[str, Any] | None,
    *,
    enabled: bool | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Return (#RRGGBB palette, change notes). No-op when disabled."""
    if not palette_refine_enabled(enabled):
        raw = {
            k: str(v).strip().upper()
            for k, v in (palette or {}).items()
            if isinstance(k, str) and v is not None
        }
        return raw, []

    notes: list[str] = ["enabled"]
    parsed: dict[str, tuple[int, int, int]] = {}
    for key in _PALETTE_KEYS:
        rgb = parse_hex((palette or {}).get(key))
        if rgb:
            parsed[key] = rgb
    before = {k: to_hex(v) for k, v in parsed.items()}
    slots = _derive_missing(parsed)
    bg = slots["bg"]
    dark = is_dark_field(bg)
    prefer_light = dark

    text, n1 = _ensure_contrast(
        slots["text"], bg, min_ratio=_MIN_TEXT_BG, prefer_light_text=prefer_light
    )
    slots["text"] = text
    notes.extend(f"text:{x}" for x in n1)

    muted, n2 = _ensure_contrast(
        slots["muted"], bg, min_ratio=_MIN_MUTED_BG, prefer_light_text=prefer_light
    )
    slots["muted"] = muted
    notes.extend(f"muted:{x}" for x in n2)

    # Keep accent readable but allow more chroma
    accent, n3 = _ensure_contrast(
        slots["accent"], bg, min_ratio=_MIN_ACCENT_BG, prefer_light_text=prefer_light
    )
    slots["accent"] = accent
    notes.extend(f"accent:{x}" for x in n3)

    accent2, n4 = _ensure_contrast(
        slots["accent2"], bg, min_ratio=_MIN_ACCENT_BG, prefer_light_text=prefer_light
    )
    slots["accent2"] = accent2
    notes.extend(f"accent2:{x}" for x in n4)

    # panel: stay near bg, slight lift
    if contrast_ratio(slots["panel"], bg) < 1.05:
        slots["panel"] = _nudge_lightness(bg, toward_light=not dark, step=0.1)
        notes.append("panel:lift")

    out = {k: to_hex(slots[k]) for k in _PALETTE_KEYS}
    changed = [k for k in _PALETTE_KEYS if before.get(k) != out[k]]
    if changed:
        notes.append("changed=" + ",".join(changed))
    else:
        notes.append("unchanged")
    return out, notes


def apply_palette_to_plan(
    plan: dict[str, Any],
    *,
    enabled: bool | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Mutate plan['palette'] when refine is on; return (plan, notes)."""
    raw = plan.get("palette") if isinstance(plan.get("palette"), dict) else {}
    refined, notes = refine_palette(raw, enabled=enabled)
    if notes and palette_refine_enabled(enabled):
        plan["palette"] = refined
    elif refined and not plan.get("palette"):
        plan["palette"] = refined
    return plan, notes
