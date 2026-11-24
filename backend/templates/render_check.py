"""Render a slide pack in a real browser and report visual quality issues.

Geometry estimation (``templates.slot_tree.measure_slots``) catches most cases but
cannot model font fallback, letter-spacing rounding or flex line boxes. This module
measures the *rendered* DOM instead:

* all leaf boxes with text, clipped by / overflowing their own box
  (``scrollWidth > clientWidth`` on overflow:hidden ancestors), and
* any text node whose bounding box escapes the 1920×1080 canvas,
* material overlap between independent text slots, and
* text/background colour conflicts and low contrast.

Two backends, in order of preference:

1. Playwright (``pip install playwright && playwright install chromium``)
2. Locally installed Chrome / Edge / Chromium in headless mode via
   ``--dump-dom`` — no extra dependency, works on macOS and CI images that ship
   Chrome.

The result is advisory: it returns findings, it never mutates the pack.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_CANVAS_W, _CANVAS_H = 1920.0, 1080.0

# Injected probe: walks every text run, reports overflow against the nearest
# clipping ancestor plus canvas escape, independent text-slot overlaps, and
# computed text/background contrast. Result is JSON in
# <body data-render-check>.
_PROBE_JS = r"""
(() => {
  const canvasW = %(w)s, canvasH = %(h)s;
  const root = document.querySelector('.pptx-slide-root') || document.body;
  const base = root.getBoundingClientRect();
  const issues = [];
  const trim = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const label = (el) => {
    const slot = el.closest('[data-slot]');
    return slot ? (slot.getAttribute('data-slot') || '?') : '(no-slot)';
  };
  const issue = (payload) => issues.push(payload);
  const visible = (el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && cs.display !== 'none' &&
      cs.visibility !== 'hidden' && Number(cs.opacity || 1) > 0.02;
  };
  const parseColor = (raw) => {
    const value = String(raw || '').trim().toLowerCase();
    if (!value || value === 'transparent') return null;
    let match = value.match(/^rgba?\((.*)\)$/);
    if (!match) return null;
    const parts = match[1].replace(/\//g, ',').split(/\s*,\s*|\s+/).filter(Boolean);
    if (parts.length < 3) return null;
    const channel = (part) => {
      if (part.endsWith('%')) return Math.max(0, Math.min(255, parseFloat(part) * 2.55));
      return Math.max(0, Math.min(255, parseFloat(part)));
    };
    const alpha = parts.length > 3 ? (parts[3].endsWith('%') ? parseFloat(parts[3]) / 100 : parseFloat(parts[3])) : 1;
    if (![parts[0], parts[1], parts[2], alpha].every((x) => Number.isFinite(parseFloat(x)))) return null;
    return { r: channel(parts[0]), g: channel(parts[1]), b: channel(parts[2]), a: Math.max(0, Math.min(1, alpha)) };
  };
  const alphaOver = (top, bottom) => {
    const ta = Math.max(0, Math.min(1, top.a));
    const ba = Math.max(0, Math.min(1, bottom.a));
    const outA = ta + ba * (1 - ta);
    if (outA <= 0.001) return { r: 255, g: 255, b: 255, a: 0 };
    return {
      r: (top.r * ta + bottom.r * ba * (1 - ta)) / outA,
      g: (top.g * ta + bottom.g * ba * (1 - ta)) / outA,
      b: (top.b * ta + bottom.b * ba * (1 - ta)) / outA,
      a: outA,
    };
  };
  const effectiveBackground = (el) => {
    const chain = [];
    let current = el;
    while (current) {
      chain.push(current);
      if (current === root) break;
      current = current.parentElement;
    }
    let bg = { r: 255, g: 255, b: 255, a: 0 };
    let hasImage = false;
    for (let i = chain.length - 1; i >= 0; i -= 1) {
      const cs = getComputedStyle(chain[i]);
      const color = parseColor(cs.backgroundColor);
      if (color && color.a > 0) bg = alphaOver(color, bg);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') hasImage = true;
    }
    // A transparent HTML canvas is rendered against the browser's white
    // viewport. Treat that as a known fallback unless an image/gradient is
    // present, so white-on-transparent text is still caught.
    if (bg.a < 0.98 && !hasImage) {
      bg = alphaOver({ r: 255, g: 255, b: 255, a: 1 }, bg);
    }
    return { color: bg, known: bg.a >= 0.98 && !hasImage };
  };
  const luminance = (color) => {
    const linear = (channel) => {
      const value = channel / 255;
      return value <= 0.03928 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * linear(color.r) + 0.7152 * linear(color.g) + 0.0722 * linear(color.b);
  };
  const contrast = (foreground, background) => {
    const a = luminance(foreground);
    const b = luminance(background);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  const colorDistance = (a, b) => Math.sqrt(
    Math.pow(a.r - b.r, 2) + Math.pow(a.g - b.g, 2) + Math.pow(a.b - b.b, 2)
  );
  const clipParent = (el) => {
    let p = el.parentElement;
    while (p && p !== root) {
      const cs = getComputedStyle(p);
      if (cs.overflow !== 'visible' || cs.overflowX !== 'visible') return p;
      p = p.parentElement;
    }
    return null;
  };
  const nodes = root.querySelectorAll('span, div');
  for (const el of nodes) {
    const own = Array.from(el.childNodes).some(
      (n) => n.nodeType === 3 && n.textContent.trim().length > 0
    );
    if (!own) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const text = (el.textContent || '').trim();
    if (!text) continue;
    const slot = label(el);
    // canvas escape (allow 1px rounding)
    if (r.right > base.left + canvasW + 1 || r.bottom > base.top + canvasH + 1) {
      issue({ kind: 'layout', severity: 'error', slot, reason: 'out_of_canvas', text: text.slice(0, 60),
        right: Math.round(r.right - base.left), bottom: Math.round(r.bottom - base.top) });
      continue;
    }
    const clip = clipParent(el);
    if (clip) {
      const cr = clip.getBoundingClientRect();
      const clipped = el.closest('[data-slot]') || clip;
      const sr = clipped.getBoundingClientRect();
      if (r.width > sr.width + 1.5) {
        issue({ kind: 'readability', severity: 'error', slot, reason: 'text_wider_than_box', text: text.slice(0, 60),
          text_px: Math.round(r.width), box_px: Math.round(sr.width) });
      }
      if (r.right > cr.right + 1.5 || r.left < cr.left - 1.5) {
        issue({ kind: 'readability', severity: 'error', slot, reason: 'clipped_horizontally', text: text.slice(0, 60),
          text_right: Math.round(r.right - base.left), clip_right: Math.round(cr.right - base.left) });
      }
      if (r.bottom > cr.bottom + 1.5) {
        issue({ kind: 'readability', severity: 'error', slot, reason: 'clipped_vertically', text: text.slice(0, 60),
          text_bottom: Math.round(r.bottom - base.top), clip_bottom: Math.round(cr.bottom - base.top) });
      }
    }

    // Check the actual rendered foreground/background colours. If the
    // background is a photo or gradient we cannot infer a single reliable
    // colour from computed CSS, so leave it for visual review instead of
    // producing a false positive.
    const styles = getComputedStyle(el);
    const foreground = parseColor(styles.color);
    const background = effectiveBackground(el);
    if (foreground && foreground.a > 0 && background.known) {
      const compositedForeground = alphaOver(foreground, background.color);
      const ratio = contrast(compositedForeground, background.color);
      const px = parseFloat(styles.fontSize || '0') || 0;
      const weight = parseInt(styles.fontWeight || '400', 10) || 400;
      const large = px >= 24 || (px >= 18.66 && weight >= 700);
      const minimum = large ? 3 : 4.5;
      const foregroundHex = [compositedForeground.r, compositedForeground.g, compositedForeground.b]
        .map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
      const backgroundHex = [background.color.r, background.color.g, background.color.b]
        .map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
      if (colorDistance(compositedForeground, background.color) <= 8 || ratio <= 1.15) {
        issue({ kind: 'color', severity: 'error', slot, reason: 'text_background_conflict', text: text.slice(0, 60),
          foreground: '#' + foregroundHex, background: '#' + backgroundHex,
          contrast_ratio: Math.round(ratio * 100) / 100 });
      } else if (ratio < minimum) {
        issue({ kind: 'color', severity: 'warning', slot, reason: 'low_contrast', text: text.slice(0, 60),
          foreground: '#' + foregroundHex, background: '#' + backgroundHex,
          contrast_ratio: Math.round(ratio * 100) / 100, minimum_contrast: minimum });
      }
    }
  }

  // Compare independent text slots. Parent/child slots are intentionally
  // ignored, as are image slots because text-over-image is a valid composition.
  const slotNodes = Array.from(root.querySelectorAll('[data-slot]'))
    .filter((el) => visible(el))
    .map((el) => {
      const type = String(el.getAttribute('data-slot-type') || '').toLowerCase();
      const text = trim(el.textContent);
      const rect = el.getBoundingClientRect();
      return { el, slot: el.getAttribute('data-slot') || '?', type, text, rect };
    })
    .filter((item) => item.text && item.type !== 'image');
  for (let i = 0; i < slotNodes.length; i += 1) {
    for (let j = i + 1; j < slotNodes.length; j += 1) {
      const a = slotNodes[i], b = slotNodes[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const overlapW = Math.max(0, Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left));
      const overlapH = Math.max(0, Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top));
      const overlap = overlapW * overlapH;
      const smaller = Math.min(a.rect.width * a.rect.height, b.rect.width * b.rect.height);
      const ratio = smaller > 0 ? overlap / smaller : 0;
      if (ratio < 0.15 || a.text === b.text) continue;
      issue({ kind: 'layout', severity: ratio >= 0.35 ? 'error' : 'warning', reason: 'layout_overlap',
        slot: a.slot + '|' + b.slot, slots: [a.slot, b.slot],
        overlap_ratio: Math.round(ratio * 1000) / 1000,
        text: a.text.slice(0, 36) + ' / ' + b.text.slice(0, 36) });
    }
  }

  // Dedupe by slot+reason, keep first sample.
  const seen = new Set();
  const out = [];
  for (const it of issues) {
    const k = (it.slot || (it.slots || []).join('|')) + '|' + it.reason;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(it);
  }
  document.body.setAttribute('data-render-check', JSON.stringify(out));
  return out;
})()
"""


def _probe_body(width: float, height: float) -> str:
    # Use literal replacement instead of ``%`` formatting because the
    # JavaScript probe legitimately contains percent signs (colour channels).
    return _PROBE_JS.replace("%(w)s", str(width)).replace("%(h)s", str(height))


def _probe_script(width: float, height: float) -> str:
    body = _probe_body(width, height)
    return f"<script>{body}</script>"


def find_browser() -> str | None:
    """Locate a Chromium-family browser binary."""
    env = os.environ.get("AI_PREPT_CHROME") or os.environ.get("CHROME_PATH")
    if env and Path(env).exists():
        return env
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _check_with_playwright(
    pages: list[Path], width: float, height: float
) -> list[dict[str, Any]] | None:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    issues: list[dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": int(width), "height": int(height)},
                device_scale_factor=1,
            )
            try:
                for path in pages:
                    page.goto(path.resolve().as_uri(), wait_until="load")
                    # Let local fonts and layout-affecting styles settle before
                    # measuring. This is deliberately short to keep agent jobs
                    # responsive while avoiding first-frame false positives.
                    page.wait_for_timeout(100)
                    found = page.evaluate(_probe_body(width, height))
                    issues.extend({**item, "file": _rel(path)} for item in found or [])
            finally:
                browser.close()
        return issues
    except Exception:  # noqa: BLE001 - fall back to local Chrome when available
        return None


_DOM_ATTR_RE = re.compile(
    r"""data-render-check="([^"]*)\"""", re.I | re.S
)


def _check_with_chrome(
    pages: list[Path], width: float, height: float, browser: str
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="render-check-") as tmp:
        profile = Path(tmp) / "profile"
        profile.mkdir()
        probe = _probe_script(width, height)
        for path in pages:
            html = path.read_text(encoding="utf-8")
            if "</body>" in html:
                probe_html = html.replace("</body>", probe + "</body>", 1)
            else:
                probe_html = html + probe
            tmp_page = Path(tmp) / path.name
            tmp_page.write_text(probe_html, encoding="utf-8")
            # Slide-relative asset paths (../theme.css, ../images) must still resolve.
            for name in ("theme.css",):
                sibling = path.parent.parent / name
                target = tmp_page.parent.parent / name
                if sibling.is_file() and not target.exists():
                    try:
                        target.write_text(sibling.read_text(encoding="utf-8"), encoding="utf-8")
                    except OSError:
                        pass
            images_src = path.parent.parent / "images"
            if images_src.is_dir():
                images_dst = tmp_page.parent.parent / "images"
                if not images_dst.exists():
                    try:
                        images_dst.symlink_to(images_src, target_is_directory=True)
                    except OSError:
                        pass
            proc = subprocess.run(
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--hide-scrollbars",
                    "--virtual-time-budget=3000",
                    f"--user-data-dir={profile}",
                    "--dump-dom",
                    tmp_page.resolve().as_uri(),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            dom = proc.stdout or ""
            m = _DOM_ATTR_RE.search(dom)
            if not m:
                continue
            raw = (
                m.group(1)
                .replace("&quot;", '"')
                .replace("&amp;", "&")
                .replace("&#x27;", "'")
            )
            try:
                found = json.loads(raw)
            except json.JSONDecodeError:
                continue
            issues.extend({**item, "file": _rel(path)} for item in found)
    return issues


def _capture_with_playwright(
    pages: list[Path],
    output_dir: Path,
    width: float,
    height: float,
) -> list[Path] | None:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency
        return None

    shots: list[Path] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": int(width), "height": int(height)},
                device_scale_factor=1,
            )
            try:
                for index, path in enumerate(pages, start=1):
                    page.goto(path.resolve().as_uri(), wait_until="networkidle")
                    page.wait_for_timeout(300)
                    shot = output_dir / f"{index:02d}.png"
                    page.locator(".pptx-slide-root").first.screenshot(path=str(shot))
                    shots.append(shot)
            finally:
                browser.close()
        return shots
    except Exception:  # noqa: BLE001 - Chrome CLI fallback below
        return None


def _capture_with_chrome(
    pages: list[Path],
    output_dir: Path,
    width: float,
    height: float,
    browser: str,
) -> list[Path]:
    shots: list[Path] = []
    profile = output_dir / ".chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(pages, start=1):
        shot = output_dir / f"{index:02d}.png"
        proc = subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=3000",
                f"--window-size={int(width)},{int(height)}",
                f"--user-data-dir={profile}",
                f"--screenshot={shot.resolve()}",
                path.resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0 or not shot.is_file() or shot.stat().st_size < 1024:
            detail = (proc.stderr or proc.stdout or "").strip()[-500:]
            raise RuntimeError(
                f"页面截图失败：{_rel(path)}" + (f"；{detail}" if detail else "")
            )
        shots.append(shot)
    return shots


def capture_package_previews(
    pack_dir: str | Path,
    output_dir: str | Path,
    *,
    page_paths: list[Path] | None = None,
    width: float = _CANVAS_W,
    height: float = _CANVAS_H,
    prefer: str = "auto",
) -> list[Path]:
    """Render every slide HTML to a full-page PNG in source order."""
    root = Path(pack_dir)
    slides = root / "slides"
    pages = (
        list(page_paths)
        if page_paths is not None
        else (sorted(slides.glob("*.html")) if slides.is_dir() else [])
    )
    if not pages:
        raise RuntimeError("模板包没有 slides/*.html，无法生成页面预览")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if prefer in {"auto", "playwright"}:
        shots = _capture_with_playwright(pages, out, width, height)
        if shots is not None:
            return shots

    browser = find_browser()
    if not browser:
        raise RuntimeError(
            "无法生成 visual-spec 页面预览：未找到 Chromium 系浏览器，"
            "也未安装 Playwright。请设置 AI_PREPT_CHROME 或安装 Chrome。"
        )
    return _capture_with_chrome(pages, out, width, height, browser)


def _rel(path: Path) -> str:
    parts = path.parts
    if "slides" in parts:
        i = parts.index("slides")
        return "/".join(parts[i:])
    return path.name


def _issue_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Return stable counts for Agent/UI consumers without changing findings."""
    by_reason: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    errors = 0
    warnings = 0
    for item in issues:
        reason = str(item.get("reason") or "unknown")
        kind = str(item.get("kind") or "layout")
        by_reason[reason] = by_reason.get(reason, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if str(item.get("severity") or "warning") == "error":
            errors += 1
        else:
            warnings += 1
    return {
        "total": len(issues),
        "errors": errors,
        "warnings": warnings,
        "by_reason": by_reason,
        "by_kind": by_kind,
        "status": "failed" if errors else ("warning" if warnings else "passed"),
    }


def check_package_render(
    pack_dir: str | Path,
    *,
    width: float = _CANVAS_W,
    height: float = _CANVAS_H,
    prefer: str = "auto",
) -> dict[str, Any]:
    """Measure rendered overflow for every slide in a pack.

    Returns ``{"engine": ..., "issues": [...], "pages": n}``; ``issues`` entries
    carry ``file`` / ``slot`` / ``reason`` / text sample and pixel numbers.
    """
    root = Path(pack_dir)
    slides = root / "slides"
    pages = sorted(slides.glob("*.html")) if slides.is_dir() else []
    if not pages:
        empty_summary = _issue_summary([])
        empty_summary["status"] = "failed"
        return {
            "engine": "none",
            "issues": [],
            "pages": 0,
            "summary": empty_summary,
            "error": "no slides",
        }

    if prefer in {"auto", "playwright"}:
        found = _check_with_playwright(pages, width, height)
        if found is not None:
            return {
                "engine": "playwright",
                "issues": found,
                "pages": len(pages),
                "summary": _issue_summary(found),
            }

    browser = find_browser()
    if not browser:
        unavailable_summary = _issue_summary([])
        unavailable_summary["status"] = "unavailable"
        return {
            "engine": "none",
            "issues": [],
            "pages": len(pages),
            "summary": unavailable_summary,
            "error": "未找到 Chromium 系浏览器，也未安装 playwright",
        }
    found = _check_with_chrome(pages, width, height, browser)
    return {
        "engine": f"chrome:{Path(browser).name}",
        "issues": found,
        "pages": len(pages),
        "summary": _issue_summary(found),
    }
