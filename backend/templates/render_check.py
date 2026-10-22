"""Render a slide pack in a real browser and report layout overflow.

Geometry estimation (``templates.slot_tree.measure_slots``) catches most cases but
cannot model font fallback, letter-spacing rounding or flex line boxes. This module
measures the *rendered* DOM instead:

* all leaf boxes with text, clipped by / overflowing their own box
  (``scrollWidth > clientWidth`` on overflow:hidden ancestors), and
* any text node whose bounding box escapes the 1920×1080 canvas.

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
# clipping ancestor plus canvas escape. Result is JSON in <body data-render-check>.
_PROBE_JS = r"""
(() => {
  const canvasW = %(w)s, canvasH = %(h)s;
  const root = document.querySelector('.pptx-slide-root') || document.body;
  const base = root.getBoundingClientRect();
  const issues = [];
  const label = (el) => {
    const slot = el.closest('[data-slot]');
    return slot ? (slot.getAttribute('data-slot') || '?') : '(no-slot)';
  };
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
      issues.push({ slot, reason: 'out_of_canvas', text: text.slice(0, 60),
        right: Math.round(r.right - base.left), bottom: Math.round(r.bottom - base.top) });
      continue;
    }
    const clip = clipParent(el);
    if (!clip) continue;
    const cr = clip.getBoundingClientRect();
    const clipped = el.closest('[data-slot]') || clip;
    const sr = clipped.getBoundingClientRect();
    if (r.width > sr.width + 1.5) {
      issues.push({ slot, reason: 'text_wider_than_box', text: text.slice(0, 60),
        text_px: Math.round(r.width), box_px: Math.round(sr.width) });
    }
    if (r.right > cr.right + 1.5 || r.left < cr.left - 1.5) {
      issues.push({ slot, reason: 'clipped_horizontally', text: text.slice(0, 60),
        text_right: Math.round(r.right - base.left), clip_right: Math.round(cr.right - base.left) });
    }
    if (r.bottom > cr.bottom + 1.5) {
      issues.push({ slot, reason: 'clipped_vertically', text: text.slice(0, 60),
        text_bottom: Math.round(r.bottom - base.top), clip_bottom: Math.round(cr.bottom - base.top) });
    }
  }
  // Dedupe by slot+reason, keep first sample.
  const seen = new Set();
  const out = [];
  for (const it of issues) {
    const k = it.slot + '|' + it.reason;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(it);
  }
  document.body.setAttribute('data-render-check', JSON.stringify(out));
  return out;
})()
"""


def _probe_script(width: float, height: float) -> str:
    body = _PROBE_JS % {"w": width, "h": height}
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
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": int(width), "height": int(height)})
        try:
            for path in pages:
                page.goto(path.resolve().as_uri(), wait_until="load")
                found = page.evaluate(_PROBE_JS % {"w": width, "h": height})
                issues.extend({**item, "file": _rel(path)} for item in found or [])
        finally:
            browser.close()
    return issues


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
        return {"engine": "none", "issues": [], "pages": 0, "error": "no slides"}

    if prefer in {"auto", "playwright"}:
        found = _check_with_playwright(pages, width, height)
        if found is not None:
            return {"engine": "playwright", "issues": found, "pages": len(pages)}

    browser = find_browser()
    if not browser:
        return {
            "engine": "none",
            "issues": [],
            "pages": len(pages),
            "error": "未找到 Chromium 系浏览器，也未安装 playwright",
        }
    found = _check_with_chrome(pages, width, height, browser)
    return {"engine": f"chrome:{Path(browser).name}", "issues": found, "pages": len(pages)}
