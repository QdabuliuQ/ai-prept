from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Union

from openai import OpenAI

from config import parse_api_keys
from image.solid_png import create_solid_color_png
from llm import _http_timeout

# Maizi / nano-banana 常用宽高比；页槽按实际版面选，勿全局锁死 16:9
ALLOWED_IMAGE_SIZES = frozenset(
    {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
)

# 占位图近似像素（与比例一致即可）
ASPECT_PLACEHOLDER_PX: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "3:2": (1200, 800),
    "2:3": (800, 1200),
}

# 硅基流动 Z-Image / Kolors 推荐分辨率（widthxheight）
SILICONFLOW_IMAGE_PX: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "3:2": (1024, 576),
    "2:3": (576, 1024),
}

ImageRefValue = Union[str, dict[str, Any]]


def normalize_image_size(raw: str | None, *, default: str = "16:9") -> str:
    """Normalize aspect / pixel size strings to API size tokens."""
    text = (raw or "").strip().lower().replace(" ", "")
    if not text or text in {"auto", "default"}:
        return default if default in ALLOWED_IMAGE_SIZES else "16:9"
    aliases = {
        "1024x1024": "1:1",
        "square": "1:1",
        "1536x1024": "16:9",
        "1792x1024": "16:9",
        "widescreen": "16:9",
        "landscape": "16:9",
        "1024x1536": "9:16",
        "portrait": "9:16",
        "1024x768": "4:3",
        "768x1024": "3:4",
        "1200x800": "3:2",
        "800x1200": "2:3",
    }
    if text in aliases:
        return aliases[text]
    if text in ALLOWED_IMAGE_SIZES:
        return text
    # "16/9" → "16:9"
    m = re.fullmatch(r"(\d+)[/:](\d+)", text)
    if m:
        cand = f"{int(m.group(1))}:{int(m.group(2))}"
        if cand in ALLOWED_IMAGE_SIZES:
            return cand
    return default if default in ALLOWED_IMAGE_SIZES else "16:9"


def placeholder_size_for_aspect(aspect: str) -> tuple[int, int]:
    size = normalize_image_size(aspect)
    return ASPECT_PLACEHOLDER_PX.get(size, (1280, 720))


def image_ref_prompt(value: ImageRefValue) -> str:
    if isinstance(value, dict):
        prompt = str(value.get("prompt") or value.get("alt") or "").strip()
        copy_safe = str(
            value.get("copy_safe_region") or value.get("image_copy_safe") or ""
        ).strip()
        focal = str(
            value.get("focal_region") or value.get("image_focal") or ""
        ).strip()
        composition: list[str] = []
        if focal:
            composition.append(f"Place the focal subject in {focal}.")
        if copy_safe:
            composition.append(
                f"Keep {copy_safe} visually quiet and low-detail for editable slide copy."
            )
        if composition:
            prompt = f"{prompt} Composition: {' '.join(composition)}".strip()
        return prompt
    return str(value or "").strip()


def image_ref_size(value: ImageRefValue, *, default: str = "16:9") -> str:
    if isinstance(value, dict):
        raw = value.get("size") or value.get("aspect") or value.get("image_aspect")
        return normalize_image_size(str(raw) if raw is not None else None, default=default)
    return normalize_image_size(None, default=default)


def infer_image_aspect(slide: dict[str, Any] | None) -> str:
    """Pick generation aspect from plan fields / geometry (not always 16:9)."""
    slide = slide or {}
    explicit = slide.get("image_aspect") or slide.get("image_size") or slide.get("aspect")
    if explicit is not None and str(explicit).strip():
        return normalize_image_size(str(explicit))

    role = str(slide.get("role") or "").strip().lower()
    blob = " ".join(
        str(slide.get(k) or "")
        for k in (
            "geometry",
            "visual_hook",
            "image_hint",
            "image_alt",
            "title",
            "core_message",
            "motif_use",
        )
    ).lower()

    circle_keys = (
        "circle",
        "circular",
        "round",
        "ring",
        "orb",
        "badge",
        "avatar",
        "mandala",
        "圆",
        "环形",
        "圆环",
        "圆形",
        "徽章",
        "头像",
        "1:1",
        "square inset",
        "方形槽",
    )
    if any(k in blob for k in circle_keys):
        return "1:1"

    portrait_keys = (
        "9:16",
        "3:4",
        "2:3",
        "portrait",
        "竖图",
        "竖幅",
        "竖版",
        "侧栏竖",
        "tall panel",
        "vertical panel",
    )
    if any(k in blob for k in portrait_keys):
        if "3:4" in blob or "竖" in blob:
            return "3:4"
        if "2:3" in blob:
            return "2:3"
        return "9:16"

    half_keys = (
        "half-bleed",
        "half bleed",
        "半版",
        "半屏",
        "split",
        "左右分栏",
        "侧栏图",
        "inset",
        "4:3",
        "3:2",
    )
    if any(k in blob for k in half_keys):
        if "3:2" in blob:
            return "3:2"
        return "4:3"

    # 满版/封面默认与画布一致
    if role in {"cover", "section", "ending"} or any(
        k in blob
        for k in (
            "full-bleed",
            "full bleed",
            "满版",
            "全出血",
            "edge-to-edge",
            "16:9",
            "widescreen",
        )
    ):
        return "16:9"

    return "16:9"


@dataclass(frozen=True)
class ImageApiConfig:
    api_keys: tuple[str, ...]
    base_url: str
    model: str
    size: str
    skip: bool
    timeout_s: float = 180.0
    max_retries: int = 1
    provider: str = "openai"
    transport: str = "openai-images"

    @property
    def api_key(self) -> str:
        return self.api_keys[0] if self.api_keys else ""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int, *, lo: int = 0, hi: int = 10) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def image_api_config() -> ImageApiConfig:
    skip = os.environ.get("AGENT_SKIP_IMAGE", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
    }
    provider = (os.environ.get("IMAGE_API_PROVIDER") or "openai").strip().lower()
    transport = (os.environ.get("IMAGE_TRANSPORT") or "").strip().lower()
    if not transport:
        if provider == "pollinations":
            transport = "pollinations-get"
        elif provider == "siliconflow":
            transport = "siliconflow-images"
        else:
            transport = "openai-images"
    # 已配置 IMAGE_* 时不再合并 OPENAI_API_KEY，避免 IDE/shell 里过期兜底 key 污染轮询池。
    dedicated = parse_api_keys(
        os.environ.get("IMAGE_API_KEYS"),
        os.environ.get("IMAGE_API_KEY"),
        os.environ.get("POLLINATIONS_API_KEYS") if provider == "pollinations" else None,
        os.environ.get("POLLINATIONS_API_KEY") if provider == "pollinations" else None,
        os.environ.get("SILICONFLOW_API_KEYS") if provider == "siliconflow" else None,
        os.environ.get("SILICONFLOW_API_KEY") if provider == "siliconflow" else None,
    )
    keys = dedicated or parse_api_keys(os.environ.get("OPENAI_API_KEY"))
    default_base = ""
    if transport == "pollinations-get":
        default_base = "https://gen.pollinations.ai"
    elif transport == "siliconflow-images":
        default_base = "https://api.siliconflow.cn/v1"
    img_base = (os.environ.get("IMAGE_API_BASE_URL") or "").strip().rstrip("/")
    poll_base = (os.environ.get("POLLINATIONS_BASE_URL") or "").strip().rstrip("/")
    openai_base = (os.environ.get("OPENAI_BASE_URL") or "").strip().rstrip("/")
    sf_base = (os.environ.get("SILICONFLOW_BASE_URL") or "").strip().rstrip("/")
    if transport == "siliconflow-images":
        # 勿被 Maizi/OpenAI 的 IMAGE_API_BASE_URL 覆盖；仅接受显式硅基流动地址
        if sf_base:
            base = sf_base
        elif img_base and "siliconflow" in img_base.lower():
            base = img_base
        else:
            base = default_base
    elif transport == "pollinations-get":
        base = poll_base or img_base or default_base
    else:
        base = img_base or openai_base or default_base
    base = base.strip().rstrip("/")
    if transport == "pollinations-get":
        default_model = "flux"
    elif transport == "siliconflow-images":
        default_model = "Tongyi-MAI/Z-Image-Turbo"
    else:
        default_model = "nano-banana-fast"
    model = (os.environ.get("IMAGE_MODEL") or default_model).strip()
    ar = (os.environ.get("IMAGE_ASPECT_RATIO") or "auto").strip()
    env_size = (os.environ.get("IMAGE_SIZE") or "").strip()
    # auto → 默认 16:9；单页仍可由 refs[file].size / image_aspect 覆盖
    if ar.lower() not in {"", "auto"}:
        size = normalize_image_size(ar)
    elif env_size:
        size = normalize_image_size(env_size)
    else:
        size = "16:9"
    needs_key = transport in {"openai-images", "pollinations-get", "siliconflow-images"}
    return ImageApiConfig(
        api_keys=keys,
        base_url=base,
        model=model,
        size=size,
        skip=skip or (needs_key and not keys) or not base,
        timeout_s=_env_float("IMAGE_TIMEOUT", _env_float("LLM_TIMEOUT", 180.0)),
        max_retries=_env_int("IMAGE_SDK_RETRIES", 1, lo=0, hi=5),
        provider=provider,
        transport=transport,
    )


def siliconflow_fallback_config(
    *,
    primary: ImageApiConfig | None = None,
) -> ImageApiConfig | None:
    """主线路失败时回退到硅基流动 Z-Image-Turbo（需 SILICONFLOW_*）。

    - 主线路是 Maizi/OpenAI/Pollinations → 回退硅基流动
    - 主线路已是硅基流动但模型不同 → 仍可回退到兜底模型（避免选错模型整包灰图）
    关闭：IMAGE_FALLBACK_SILICONFLOW=0
    """
    if not _env_truthy("IMAGE_FALLBACK_SILICONFLOW", default=True):
        return None
    keys = parse_api_keys(
        os.environ.get("SILICONFLOW_API_KEYS"),
        os.environ.get("SILICONFLOW_API_KEY"),
        # 主线路已是 siliconflow 时 keys 可能只在 IMAGE_API_KEYS
        os.environ.get("IMAGE_API_KEYS")
        if primary is not None and primary.transport == "siliconflow-images"
        else None,
        os.environ.get("IMAGE_API_KEY")
        if primary is not None and primary.transport == "siliconflow-images"
        else None,
    )
    if not keys:
        return None
    model = (
        os.environ.get("IMAGE_FALLBACK_SILICONFLOW_MODEL")
        or "Tongyi-MAI/Z-Image-Turbo"
    ).strip()
    if (
        primary is not None
        and primary.transport == "siliconflow-images"
        and (primary.model or "").strip() == model
    ):
        # 主线路已经是兜底模型，无需再回退
        return None
    base = (
        os.environ.get("SILICONFLOW_BASE_URL")
        or "https://api.siliconflow.cn/v1"
    ).strip().rstrip("/")
    # 主线路硅基流动时 IMAGE_API_BASE_URL 可能已被写成硅基地址
    if primary is not None and primary.transport == "siliconflow-images":
        pb = (primary.base_url or "").strip().rstrip("/")
        if pb and "siliconflow" in pb.lower():
            base = pb
    timeout = (
        primary.timeout_s
        if primary is not None
        else _env_float("IMAGE_TIMEOUT", _env_float("LLM_TIMEOUT", 180.0))
    )
    size = primary.size if primary is not None else "16:9"
    return ImageApiConfig(
        api_keys=keys,
        base_url=base,
        model=model,
        size=size,
        skip=False,
        timeout_s=timeout,
        max_retries=_env_int("IMAGE_SDK_RETRIES", 1, lo=0, hi=5),
        provider="siliconflow",
        transport="siliconflow-images",
    )


class ImageClientPool:
    def __init__(self, cfg: ImageApiConfig):
        self.cfg = cfg
        timeout = _http_timeout(cfg.timeout_s)
        self._clients = [
            OpenAI(
                api_key=key,
                base_url=cfg.base_url,
                timeout=timeout,
                max_retries=cfg.max_retries,
            )
            for key in cfg.api_keys
        ]
        self._keys = list(cfg.api_keys)
        self._i = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._clients)

    def next(self) -> tuple[OpenAI, str]:
        with self._lock:
            idx = self._i % len(self._clients)
            self._i += 1
            return self._clients[idx], self._keys[idx]


def make_image_client(cfg: ImageApiConfig) -> OpenAI:
    return OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=_http_timeout(cfg.timeout_s),
        max_retries=cfg.max_retries,
    )


def make_image_client_pool(cfg: ImageApiConfig) -> ImageClientPool:
    return ImageClientPool(cfg)


# <img src="../images/…"> 以及偶发的
# <div data-element="image" src|data-src="../images/…">（属性可跨行）
_LOCAL_IMG_ATTR_RE = re.compile(
    r"""<(?P<tag>[\w-]+)\b(?P<attrs>[^>]*?\b(?:src|data-src)=["']\.\./images/(?P<name>[^"'?#]+)(?:[?#][^"']*)?["'][^>]*)>""",
    re.I,
)
_ALT_RE = re.compile(r"""\b(?:alt|data-alt)=["']([^"']*)["']""", re.I)
_BOX_WH_RE = re.compile(
    r"""width\s*:\s*([\d.]+)\s*px.*?height\s*:\s*([\d.]+)\s*px"""
    r"""|height\s*:\s*([\d.]+)\s*px.*?width\s*:\s*([\d.]+)\s*px""",
    re.I | re.S,
)


def aspect_token_from_box(width_px: float, height_px: float) -> str:
    """Map slot box to nearest allowed aspect token."""
    if width_px <= 0 or height_px <= 0:
        return "16:9"
    ratio = width_px / height_px
    candidates = (
        (1, 1),
        (16, 9),
        (9, 16),
        (4, 3),
        (3, 4),
        (3, 2),
        (2, 3),
    )
    best = min(candidates, key=lambda ab: abs(ratio - (ab[0] / ab[1])))
    return f"{best[0]}:{best[1]}"


def _infer_slot_aspect_near(html: str, img_start: int) -> str | None:
    """Look at enclosing markup before <img> for absolute width/height px."""
    window = html[max(0, img_start - 1200) : img_start]
    # Prefer innermost data-slot-type=image container
    slot_idx = window.rfind("data-slot-type")
    chunk = window[slot_idx:] if slot_idx >= 0 else window[-600:]
    m = _BOX_WH_RE.search(chunk)
    if not m:
        return None
    if m.group(1) is not None:
        w, h = float(m.group(1)), float(m.group(2))
    else:
        h, w = float(m.group(3)), float(m.group(4))
    return aspect_token_from_box(w, h)


def collect_local_images(html_pages: list[str]) -> dict[str, ImageRefValue]:
    """filename -> prompt hint，尽量带上槽位 size（避免竖槽硬塞 16:9 再被拉伸）。"""
    out: dict[str, ImageRefValue] = {}
    for html in html_pages:
        for m in _LOCAL_IMG_ATTR_RE.finditer(html):
            name = (m.group("name") or "").strip()
            if not name or "/" in name or "\\" in name or ".." in name:
                continue
            alt_m = _ALT_RE.search(m.group("attrs") or "")
            alt = (alt_m.group(1).strip() if alt_m else "") or ""
            size = _infer_slot_aspect_near(html, m.start())
            prev = out.get(name)
            prev_prompt = image_ref_prompt(prev) if prev is not None else ""
            prev_size = (
                image_ref_size(prev)
                if isinstance(prev, dict)
                else None
            )
            prompt = alt if (alt and len(alt) >= len(prev_prompt)) else prev_prompt
            final_size = size or prev_size
            if final_size:
                out[name] = {"prompt": prompt or name, "size": final_size}
            else:
                out[name] = prompt or name
    return out


def normalize_img_object_fit(html: str, *, fit: str = "cover") -> str:
    """PPTX 转换曾写 object-fit:fill（拉伸变形）；统一为 cover 保比例裁切。"""
    fit = (fit or "cover").strip().lower() or "cover"
    return re.sub(
        r"(object-fit\s*:\s*)fill\b",
        rf"\1{fit}",
        html,
        flags=re.I,
    )

def extract_theme_bg(theme_css: str) -> str | None:
    """从 theme.css 提取主背景色（--bg / --color-bg / background）。"""
    colors = extract_theme_colors(theme_css)
    return colors.get("bg")


def extract_theme_colors(theme_css: str) -> dict[str, str]:
    """提取画布/材质相关色标，供同包生图材质锁定。"""
    out: dict[str, str] = {}
    specs: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("bg", ("--bg", "--color-bg", "--background")),
        ("surface", ("--surface", "--paper", "--color-surface")),
        ("primary", ("--primary", "--color-primary", "--accent")),
        ("ink", ("--ink", "--color-ink", "--fg", "--color-fg", "--text")),
    )
    for role, vars_ in specs:
        for var in vars_:
            m = re.search(
                rf"{re.escape(var)}\s*:\s*(#[0-9A-Fa-f]{{3,8}})",
                theme_css,
            )
            if m:
                out[role] = m.group(1)
                break
    return out


def _infer_material_family(blob: str) -> str:
    """从 style/alt 推断材质家族：ink | photo | wash | illustration。"""
    b = blob.lower()
    ink_keys = (
        "水墨",
        "墨",
        "宣纸",
        "湖墨",
        "shuimo",
        "ink wash",
        "ink-wash",
        "sumi",
    )
    if any(k in b for k in ink_keys):
        return "ink"
    wash_keys = (
        "wash",
        "纸纹",
        "纹理",
        "氛围",
        "雾面",
        "texture",
        "paper",
        "gradient",
        "渐变",
    )
    if any(k in b for k in wash_keys):
        return "wash"
    photo_keys = (
        "电影",
        "摄影",
        "实景",
        "风景",
        "cinematic",
        "photograph",
        "photo",
        "aerial",
        "landscape",
    )
    if any(k in b for k in photo_keys):
        return "photo"
    return "illustration"


def build_shared_material_lock(
    *,
    style_hint: str,
    bg_hex: str | None = None,
    alts: list[str] | None = None,
    theme_colors: dict[str, str] | None = None,
) -> str:
    """
    整包共用材质锁定：色、纸感、颗粒、光感一致；槽位只改职责/浓淡，不另起炉灶。
    解决同页多图「各说各话」导致的搭配突兀。
    """
    colors = dict(theme_colors or {})
    bg = (bg_hex or colors.get("bg") or "#0B1220").strip()
    surface = (colors.get("surface") or bg).strip()
    primary = (colors.get("primary") or "").strip()
    ink = (colors.get("ink") or "").strip()
    style = (style_hint or "").strip()
    alt_blob = " ".join(a for a in (alts or []) if a).strip()
    family = _infer_material_family(f"{style} {alt_blob}")

    palette = f"canvas/base {bg}, paper/surface {surface}"
    if primary:
        palette += f", accent {primary}"
    if ink:
        palette += f", ink/fg {ink}"

    common = (
        "SHARED MATERIAL LOCK (identical across every asset in this deck): "
        f"one cohesive suite — same paper/grain, same color temperature, same lighting grade; "
        f"palette {palette}. "
        "Do NOT invent a second paper stock, colder grain, or unrelated palette. "
        "No text, logos, watermarks, UI chrome, photo frames, or hard white borders. "
    )

    if family == "ink":
        family_line = (
            "Family: traditional Chinese ink-wash on one warm Xuan-paper tone; "
            "soft bleeding edges; ink density may vary by slot but hue/paper must match siblings. "
        )
    elif family == "wash":
        family_line = (
            "Family: abstract atmospheric wash / fine paper texture; "
            "seamless soft transitions; no hard geometric crop boxes inside the artwork. "
        )
    elif family == "photo":
        family_line = (
            "Family: cinematic editorial photography; "
            "same white-balance, contrast curve, and material light as sibling assets. "
        )
    else:
        family_line = (
            "Family: refined editorial illustration; "
            "same line weight, fill language, and paper field as sibling assets. "
        )

    style_bit = f"Deck style intent: {style}. " if style else ""
    return common + family_line + style_bit


def _slot_role_hint(filename: str, alt: str) -> str:
    """槽位只描述职责/浓淡位置，不另开材质。"""
    stem = Path(filename).stem.lower()
    blob = f"{stem} {alt}".lower()
    if any(
        k in blob
        for k in (
            "corner",
            "ornament",
            "角",
            "tl",
            "tr",
            "bl",
            "br",
            "top-left",
            "bottom-right",
            "top_left",
            "bottom_right",
        )
    ):
        denser = any(
            k in blob for k in ("br", "bottom", "右下", "下", "浓", "deep", "dark")
        )
        lighter = any(
            k in blob for k in ("tl", "top", "左上", "上", "淡", "light", "soft")
        )
        dens = (
            "slightly denser ink/wash in this corner only"
            if denser
            else (
                "lighter/softer wash in this corner only"
                if lighter
                else "corner accent only — softer than a full hero"
            )
        )
        return (
            f"Slot: diagonal/corner companion in the SAME material suite ({dens}); "
            "subject must feel cut from the same sheet as siblings, not a separate sticker. "
        )
    if "wash" in stem or any(k in blob for k in ("洗色", "纸纹", "氛围底")):
        return "Slot: full-field atmospheric wash / paper; no focal object competing with type. "
    if any(k in stem for k in ("cover", "hero", "section", "chapter", "closing")):
        return "Slot: primary hero / cover visual; still obey the shared material lock. "
    return "Slot: page asset in the shared suite; only subject/role differs from siblings. "


def build_image_prompt(
    *,
    filename: str,
    alt: str,
    style_hint: str,
    bg_hex: str | None = None,
    material_lock: str | None = None,
    aspect: str | None = None,
) -> str:
    stem = Path(filename).stem.replace("-", " ").replace("_", " ")
    subject = alt.strip() or stem
    style = style_hint.strip() or "clean editorial presentation visual"
    bg = bg_hex or "#0B1220"
    ratio = normalize_image_size(aspect)
    blob = f"{style} {subject} {stem}".lower()
    lock = (material_lock or "").strip()
    if not lock:
        lock = build_shared_material_lock(
            style_hint=style,
            bg_hex=bg,
            alts=[subject],
        )
    slot = _slot_role_hint(filename, subject)
    frame = (
        f"Canvas aspect {ratio}. Fill the entire canvas edge-to-edge; "
        "compose the subject for this exact ratio. "
        "Every pixel is photographic content — the scene continues to all four edges. "
        "Never add black bars, letterboxing, pillarboxing, padded margins, "
        "photo frames, mats, passepartout, polaroid borders, gallery walls, "
        "or a floating picture on a solid background. "
    )
    anti_matte = (
        "CRITICAL OUTPUT RULE: Do NOT draw an inset photo inside a dark/gray field. "
        "Forbidden: framed print, white border around a small photo, chalkboard matte, "
        "or any solid-color surround. Full-bleed only. "
    )

    cinematic_keys = (
        "电影",
        "摄影",
        "全出血",
        "实景",
        "风景",
        "cinematic",
        "photograph",
        "photo",
        "aerial",
        "landscape",
        "villa",
        "湖",
        "山",
        "雾",
        "建筑",
        "文旅",
        "度假",
        "沉浸",
        "治愈自然",
        "hero",
        "cover",
        "主视觉",
    )
    watercolor_keys = (
        "水彩",
        "手作",
        "剪影",
        "插画",
        "拼贴",
        "马赛克",
        "青春",
        "几何人物",
        "低多边形",
        "工作坊",
        "silhouette",
        "watercolor",
        "collage",
        "mosaic",
        "水墨",
        "墨",
    )
    wash_keys = (
        "wash",
        "gradient",
        "纹理",
        "纸纹",
        "渐变",
        "氛围",
        "雾面",
        "texture",
        "paper",
    )

    is_cinematic = any(k.lower() in blob for k in cinematic_keys)
    is_watercolor = any(k.lower() in blob for k in watercolor_keys)
    is_wash = any(k.lower() in blob for k in wash_keys)
    # 文件名含 cover/hero/section → 强制电影感全出血，避免扁平插画小图
    stem_l = stem.lower()
    force_hero = any(
        k in stem_l
        for k in ("cover", "hero", "section", "chapter", "closing", "title", "wash")
    )

    if is_wash or (force_hero and "wash" in stem_l):
        body = (
            f"{frame}{anti_matte}Full-bleed abstract atmospheric wash or fine paper texture. "
            "Soft subtle color transition (gradient-like), seamless edge-to-edge, "
            "no text, no logos, no watermark, no UI chrome, no hard shapes, no icons. "
            f"Harmonize with slide color {bg}. "
            f"{slot}Subject intent: {subject}."
        )
    elif is_cinematic or force_hero:
        body = (
            f"{frame}{anti_matte}Cinematic full-bleed photograph. "
            "No text, no logos, no watermark, no UI chrome, no frame, no white border, no collage. "
            "Atmospheric lighting, shallow depth of field, moody editorial photography. "
            "Premium magazine cover quality, rich material and light. "
            f"{slot}Subject: {subject}."
        )
    elif is_watercolor:
        body = (
            f"{frame}{anti_matte}Presentation illustration. "
            "No text, no logos, no watermark, no UI chrome. "
            "Warm watercolor / ink-wash paper texture or refined editorial illustration, "
            "not cute stickers; match sibling assets exactly in paper and ink temperature. "
            f"{slot}Subject: {subject}."
        )
    else:
        body = (
            f"{frame}{anti_matte}High-quality presentation illustration for a slide template. "
            "No text, no logos, no watermark, no UI chrome, no photo frame, no card border. "
            f"Background must be a seamless flat/near-flat field matching slide color {bg} "
            f"(exact same hue/value if possible), so the asset can sit on a {bg} slide without a visible rectangle. "
            "Subject floats softly with gentle falloff into that background; avoid hard cropped box edges. "
            f"{slot}Subject: {subject}."
        )

    return f"{lock}{body}"


def estimate_inset_matte_ratio(data: bytes, *, dark_thresh: int = 90) -> float:
    """粗测「深灰垫底 + 小图嵌套」失败：近均匀深灰像素占比（0~1）。"""
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return 0.0
    try:
        im = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return 0.0
    # 降采样，避免大图拖慢流水线
    im = im.resize((64, 64))
    dark = 0
    total = 0
    for r, g, b in im.getdata():
        total += 1
        if abs(r - g) < 12 and abs(g - b) < 12 and (r + g + b) / 3.0 < dark_thresh:
            dark += 1
    return dark / max(1, total)


def defit_inset_matte(data: bytes, *, dark_thresh: int = 90) -> bytes | None:
    """若整图画布被深灰垫底 + 小照片嵌套，裁掉垫底并拉回原尺寸。

    无法可靠识别时返回 None（调用方保留原图）。
    """
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    if w < 32 or h < 32:
        return None
    px = im.load()
    assert px is not None

    def _is_matte(x: int, y: int) -> bool:
        r, g, b = px[x, y]
        return abs(r - g) < 12 and abs(g - b) < 12 and (r + g + b) / 3.0 < dark_thresh

    # 粗网格找内容包围盒，比逐像素快
    step = max(1, min(w, h) // 128)
    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if not _is_matte(x, y):
                xs.append(x)
                ys.append(y)
    if len(xs) < 8:
        return None
    left, right = max(0, min(xs) - step * 2), min(w, max(xs) + step * 2)
    top, bottom = max(0, min(ys) - step * 2), min(h, max(ys) + step * 2)
    cw, ch = right - left, bottom - top
    # 内容区太小（仍像贴纸）或几乎满版（无需裁）则跳过
    coverage = (cw * ch) / float(w * h)
    if coverage < 0.12 or coverage > 0.92:
        return None
    cropped = im.crop((left, top, right, bottom))
    # 保持目标画布比例：按原 w:h 中心扩展裁切后再缩放
    target_ar = w / h
    c_ar = cw / max(1, ch)
    if c_ar > target_ar:
        # 太宽 → 加高
        new_h = int(round(cw / target_ar))
        pad = max(0, new_h - ch)
        t2 = max(0, top - pad // 2)
        b2 = min(h, t2 + new_h)
        t2 = max(0, b2 - new_h)
        cropped = im.crop((left, t2, right, b2))
    elif c_ar < target_ar:
        new_w = int(round(ch * target_ar))
        pad = max(0, new_w - cw)
        l2 = max(0, left - pad // 2)
        r2 = min(w, l2 + new_w)
        l2 = max(0, r2 - new_w)
        cropped = im.crop((l2, top, r2, bottom))
    out = cropped.resize((w, h), Image.Resampling.LANCZOS)
    buf = BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


_REMATTE_SUFFIX = (
    " REGENERATE CONSTRAINT: previous attempt looked like a small framed photo on a "
    "solid dark matte — that is WRONG. Output must be one continuous photograph "
    "filling 100% of the canvas with zero border, zero matte, zero inset."
)

def _download(url: str, *, timeout: int = 120) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
        return r.read()


def aspect_to_pixels(aspect: str) -> tuple[int, int]:
    """Map aspect tokens to Pollinations width/height."""
    return ASPECT_PLACEHOLDER_PX.get(normalize_image_size(aspect), (1280, 720))


def aspect_to_siliconflow_image_size(aspect: str) -> str:
    """Map aspect → SiliconFlow `image_size` (widthxheight)."""
    w, h = SILICONFLOW_IMAGE_PX.get(
        normalize_image_size(aspect),
        (1024, 576),
    )
    return f"{w}x{h}"


def generate_image_bytes_siliconflow(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    timeout_s: float = 180.0,
) -> bytes:
    """POST /v1/images/generations（硅基流动：image_size + 可选关水印）。"""
    root = base_url.rstrip("/")
    if not root.endswith("/v1"):
        root = f"{root}/v1"
    url = f"{root}/images/generations"
    payload = {
        "model": model or "Tongyi-MAI/Z-Image-Turbo",
        "prompt": prompt,
        "image_size": aspect_to_siliconflow_image_size(size),
        "batch_size": 1,
    }
    # Kolors 支持额外采样参数；Z-Image 不需要
    if "Kolors" in str(model or ""):
        payload["num_inference_steps"] = 20
        payload["guidance_scale"] = 7.5
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Enable-Watermark": "0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(timeout_s)) as r:  # noqa: S310
            raw = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise RuntimeError(
            f"硅基流动生图失败 HTTP {e.code}: {err_body or e.reason}"
        ) from e

    images = raw.get("images") if isinstance(raw, dict) else None
    data_list = raw.get("data") if isinstance(raw, dict) else None
    candidates: list[Any] = []
    if isinstance(images, list):
        candidates.extend(images)
    if isinstance(data_list, list):
        candidates.extend(data_list)

    for item in candidates:
        if isinstance(item, str) and item.startswith("http"):
            return _download(item)
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json") or item.get("image")
        if isinstance(b64, str) and b64.strip():
            # 可能带 data:image/...;base64, 前缀
            if "," in b64[:64]:
                b64 = b64.split(",", 1)[1]
            return base64.b64decode(b64)
        url_val = item.get("url")
        if isinstance(url_val, str) and url_val.strip():
            return _download(url_val.strip())

    raise RuntimeError(f"硅基流动未返回图片 url/b64: {str(raw)[:400]}")


def generate_image_bytes_pollinations(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    timeout_s: float = 180.0,
) -> bytes:
    """GET https://gen.pollinations.ai/image/{prompt}?model=&width=&height=&key="""
    import urllib.parse

    w, h = aspect_to_pixels(size)
    root = base_url.rstrip("/").removesuffix("/v1")
    encoded = urllib.parse.quote(prompt, safe="")
    qs = urllib.parse.urlencode(
        {
            "model": model or "flux",
            "width": str(w),
            "height": str(h),
            "nologo": "true",
            "key": api_key,
        }
    )
    url = f"{root}/image/{encoded}?{qs}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(timeout_s)) as r:  # noqa: S310
            data = r.read()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise RuntimeError(
            f"Pollinations 生图失败 HTTP {e.code}: {body or e.reason}"
        ) from e
    if not data or len(data) < 100:
        raise RuntimeError("Pollinations 返回空图或过短响应")
    if sniff_image_suffix(data) is None:
        preview = data[:120].decode("utf-8", errors="replace")
        raise RuntimeError(f"Pollinations 未返回图片字节: {preview}")
    from usage import record_image_usage

    record_image_usage(None, images=1)
    return data


def _poll_task(
    *,
    base_url: str,
    api_key: str,
    task_id: str,
    timeout_s: float = 180,
    interval_s: float = 1.5,
) -> bytes:
    """Maizi 异步任务：GET /tasks/{id} → result_urls。"""
    url = f"{base_url.rstrip('/')}/tasks/{task_id}"
    deadline = time.time() + timeout_s
    last_status = ""
    while time.time() < deadline:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"轮询任务失败 HTTP {e.code}: {task_id}") from e

        status = str(data.get("status") or "").lower()
        last_status = status
        urls = data.get("result_urls") or data.get("urls") or []
        if isinstance(urls, str):
            urls = [urls]
        if status in {"completed", "succeeded", "success", "done"} and urls:
            return _download(str(urls[0]))
        if status in {"failed", "error", "cancelled"}:
            msg = data.get("error_msg") or data.get("error") or status
            raise RuntimeError(f"生图任务失败: {msg}")
        time.sleep(interval_s)
    raise RuntimeError(f"生图任务超时 status={last_status} task_id={task_id}")


def generate_image_bytes(
    client: OpenAI | None,
    *,
    model: str,
    prompt: str,
    size: str,
    api_key: str,
    base_url: str,
    transport: str = "openai-images",
    timeout_s: float = 180.0,
) -> bytes:
    if transport == "pollinations-get":
        return generate_image_bytes_pollinations(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            size=size,
            timeout_s=timeout_s,
        )
    if transport == "siliconflow-images":
        data = generate_image_bytes_siliconflow(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            size=size,
            timeout_s=timeout_s,
        )
        from usage import record_image_usage

        record_image_usage(None, images=1)
        return data
    if client is None:
        raise RuntimeError("OpenAI images 客户端未初始化")
    resp = client.images.generate(
        model=model,
        prompt=prompt,
        size=size,  # type: ignore[arg-type]
        n=1,
    )
    from usage import record_image_usage

    usage = getattr(resp, "usage", None)
    if usage is None and hasattr(resp, "model_dump"):
        raw_resp = resp.model_dump()
        usage = raw_resp.get("usage") if isinstance(raw_resp, dict) else None
    record_image_usage(usage, images=1)

    item = resp.data[0]
    raw = item.model_dump() if hasattr(item, "model_dump") else {}

    b64 = getattr(item, "b64_json", None) or raw.get("b64_json")
    if b64:
        return base64.b64decode(b64)

    url = getattr(item, "url", None) or raw.get("url")
    if url:
        return _download(str(url))

    task_id = raw.get("task_id") or getattr(item, "task_id", None)
    if task_id:
        return _poll_task(base_url=base_url, api_key=api_key, task_id=str(task_id))

    raise RuntimeError(
        f"images.generate 未返回 b64_json/url/task_id: {raw or item}"
    )


def _is_real_image(path: Path) -> bool:
    """纯色占位通常很小；真实 JPEG/PNG 一般 > 20KB。"""
    try:
        return path.is_file() and path.stat().st_size > 20_000
    except OSError:
        return False


def sniff_image_suffix(data: bytes) -> str | None:
    """Detect raster container from magic bytes → .png / .jpg / .webp."""
    if not data or len(data) < 12:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def coerce_image_bytes_to_suffix(data: bytes, suffix: str) -> bytes:
    """Ensure bytes match the filename extension (Maizi often returns JPEG as .png)."""
    want = (suffix or "").lower()
    if want == ".jpeg":
        want = ".jpg"
    sniffed = sniff_image_suffix(data)
    if not want or not sniffed:
        return data
    if want == sniffed:
        return data
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            f"图片格式为 {sniffed}，目标为 {want}，需要 Pillow 转换：pip install pillow"
        ) from exc

    im = Image.open(BytesIO(data))
    out = BytesIO()
    if want == ".png":
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    if want == ".jpg":
        if im.mode in ("RGBA", "P"):
            im = im.convert("RGB")
        im.save(out, format="JPEG", quality=92, optimize=True)
        return out.getvalue()
    if want == ".webp":
        im.save(out, format="WEBP", quality=90)
        return out.getvalue()
    return data


def write_image_bytes(dest: Path, data: bytes) -> Path:
    """Write image bytes, converting when magic ≠ extension (keeps dest name stable)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = coerce_image_bytes_to_suffix(data, dest.suffix.lower())
    dest.write_bytes(payload)
    return dest


def _default_image_concurrency(key_count: int = 1) -> int:
    raw = os.environ.get("AGENT_IMAGE_CONCURRENCY", "").strip()
    if raw:
        try:
            return max(1, min(int(raw), 8))
        except ValueError:
            pass
    return max(1, min(max(1, key_count) * 2, 8))


def materialize_images(
    images_dir: Path,
    refs: dict[str, ImageRefValue],
    *,
    style_hint: str = "",
    bg_hex: str | None = None,
    theme_colors: dict[str, str] | None = None,
    concurrency: int | None = None,
    force: bool = False,
) -> list[str]:
    """按 HTML/规划引用生成/补齐 images/；返回警告列表。失败只写占位，不抛异常。

    refs 值可为 str（提示词，比例用全局默认）或
    ``{"prompt": "...", "size": "1:1"|"16:9"|...}``（按槽位比例生图）。
    force=True 时即使已有真实图片也会重新生成（覆写），避免先删后写造成预览 404。
    """
    warnings: list[str] = []
    if not refs:
        return warnings

    images_dir.mkdir(parents=True, exist_ok=True)
    cfg = image_api_config()
    pool: ImageClientPool | None = None
    key_ring: list[str] = list(cfg.api_keys)
    use_pollinations = cfg.transport == "pollinations-get"
    use_siliconflow = cfg.transport == "siliconflow-images"
    use_http_only = use_pollinations or use_siliconflow
    if not cfg.skip:
        if use_pollinations:
            if not key_ring:
                warnings.append("Pollinations 未配置 IMAGE_/POLLINATIONS_ API Key，改用占位图")
            else:
                print(
                    f"文生图后端: Pollinations GET · model={cfg.model} · {cfg.base_url}",
                    flush=True,
                )
        elif use_siliconflow:
            if not key_ring:
                warnings.append("硅基流动未配置 SILICONFLOW_/IMAGE_ API Key，改用占位图")
            else:
                print(
                    f"文生图后端: SiliconFlow · model={cfg.model} · {cfg.base_url}",
                    flush=True,
                )
        else:
            try:
                pool = make_image_client_pool(cfg)
            except Exception as e:
                warnings.append(f"文生图客户端初始化失败，改用占位图: {e}")
                pool = None
            else:
                print(
                    f"文生图后端: {cfg.provider} · model={cfg.model} · {cfg.base_url}",
                    flush=True,
                )

    sf_preview = siliconflow_fallback_config(primary=cfg)
    if sf_preview is not None:
        print(
            f"文生图回退就绪: SiliconFlow · model={sf_preview.model} · {sf_preview.base_url}",
            flush=True,
        )
    pending: list[tuple[str, ImageRefValue]] = []
    for filename, alt in refs.items():
        dest = images_dir / filename
        if not force and _is_real_image(dest):
            continue
        pending.append((filename, alt))

    if not pending:
        return warnings

    # 整包一次材质锁定：同套纸色/温度/颗粒，槽位只改职责
    all_prompts = [image_ref_prompt(v) for v in refs.values()]
    material_lock = build_shared_material_lock(
        style_hint=style_hint,
        bg_hex=bg_hex,
        alts=[image_ref_prompt(v) for _, v in pending] + all_prompts,
        theme_colors=theme_colors,
    )

    # 闭包捕获 ImageClientPool；勿与下方 ThreadPoolExecutor 同名，否则运行时
    # 会变成 executor.next() → AttributeError。
    image_pool = pool
    key_i = {"n": 0}
    key_lock = threading.Lock()
    from usage import current_usage, use_usage

    parent_usage = current_usage()

    def _next_key() -> str:
        with key_lock:
            if not key_ring:
                return ""
            idx = key_i["n"] % len(key_ring)
            key_i["n"] += 1
            return key_ring[idx]

    sf_fallback = siliconflow_fallback_config(primary=cfg)
    sf_key_i = {"n": 0}
    sf_key_lock = threading.Lock()
    sf_keys = list(sf_fallback.api_keys) if sf_fallback else []

    def _next_sf_key() -> str:
        with sf_key_lock:
            if not sf_keys:
                return ""
            idx = sf_key_i["n"] % len(sf_keys)
            sf_key_i["n"] += 1
            return sf_keys[idx]

    def _one(filename: str, ref: ImageRefValue) -> str | None:
        with use_usage(parent_usage):
            dest = images_dir / filename
            alt = image_ref_prompt(ref)
            size = image_ref_size(ref, default=cfg.size)
            ph_w, ph_h = placeholder_size_for_aspect(size)
            can_generate = (
                (use_http_only and bool(key_ring) and not cfg.skip)
                or (not use_http_only and image_pool is not None)
            )
            if not can_generate and not sf_fallback:
                dest.write_bytes(create_solid_color_png(ph_w, ph_h, (180, 180, 185)))
                return f"跳过生图，占位: {filename} ({size})"
            prompt = build_image_prompt(
                filename=filename,
                alt=alt,
                style_hint=style_hint,
                bg_hex=bg_hex,
                material_lock=material_lock,
                aspect=size,
            )

            def _write_ok(data: bytes, *, via: str) -> None:
                sniffed = sniff_image_suffix(data)
                write_image_bytes(dest, data)
                note = ""
                if sniffed and sniffed != dest.suffix.lower():
                    note = f"，已从 {sniffed} 转为 {dest.suffix.lower()}"
                print(
                    f"文生图完成{via}: {filename} [{size}] "
                    f"({dest.stat().st_size} bytes{note})",
                    flush=True,
                )

            def _gen_reject_matte(
                *,
                client: OpenAI | None,
                api_key: str,
                base_url: str,
                transport: str,
                model: str,
                timeout_s: float,
                prompt_text: str,
            ) -> bytes:
                data = generate_image_bytes(
                    client,
                    model=model,
                    prompt=prompt_text,
                    size=size,
                    api_key=api_key,
                    base_url=base_url,
                    transport=transport,
                    timeout_s=timeout_s,
                )
                ratio = estimate_inset_matte_ratio(data)
                if ratio >= 0.55:
                    print(
                        f"文生图检测到垫底/嵌套相框 {filename} "
                        f"(dark≈{ratio:.0%})，加强满版约束重试 …",
                        flush=True,
                    )
                    data = generate_image_bytes(
                        client,
                        model=model,
                        prompt=prompt_text + _REMATTE_SUFFIX,
                        size=size,
                        api_key=api_key,
                        base_url=base_url,
                        transport=transport,
                        timeout_s=timeout_s,
                    )
                    ratio = estimate_inset_matte_ratio(data)
                if ratio >= 0.45:
                    cropped = defit_inset_matte(data)
                    if cropped is not None:
                        new_r = estimate_inset_matte_ratio(cropped)
                        print(
                            f"文生图垫底裁切 {filename}: "
                            f"dark {ratio:.0%} → {new_r:.0%}",
                            flush=True,
                        )
                        data = cropped
                return data

            primary_err: Exception | None = None
            if can_generate:
                try:
                    client: OpenAI | None = None
                    api_key = ""
                    if use_http_only:
                        api_key = _next_key()
                    else:
                        assert image_pool is not None
                        client, api_key = image_pool.next()
                    print(f"文生图: {filename} [{size}] …", flush=True)
                    data = _gen_reject_matte(
                        client=client,
                        api_key=api_key,
                        base_url=cfg.base_url,
                        transport=cfg.transport,
                        model=cfg.model,
                        timeout_s=cfg.timeout_s,
                        prompt_text=prompt,
                    )
                    _write_ok(data, via="")
                    return None
                except Exception as e:
                    primary_err = e
                    print(
                        f"文生图主线路失败 {filename} [{size}]: {e}",
                        flush=True,
                    )

            if sf_fallback is not None:
                try:
                    sf_key = _next_sf_key()
                    print(
                        f"文生图回退硅基流动: {filename} [{size}] "
                        f"model={sf_fallback.model} …",
                        flush=True,
                    )
                    data = _gen_reject_matte(
                        client=None,
                        api_key=sf_key,
                        base_url=sf_fallback.base_url,
                        transport="siliconflow-images",
                        model=sf_fallback.model,
                        timeout_s=sf_fallback.timeout_s,
                        prompt_text=prompt,
                    )
                    _write_ok(data, via="（硅基流动回退）")
                    return None
                except Exception as e2:
                    dest.write_bytes(
                        create_solid_color_png(ph_w, ph_h, (180, 180, 185))
                    )
                    if primary_err is not None:
                        return (
                            f"生图失败 {filename} [{size}]: "
                            f"primary={primary_err}; siliconflow={e2}"
                        )
                    return f"生图失败 {filename} [{size}]（硅基流动）: {e2}"

            dest.write_bytes(create_solid_color_png(ph_w, ph_h, (180, 180, 185)))
            if primary_err is not None:
                return f"生图失败 {filename} [{size}]: {primary_err}"
            return f"跳过生图，占位: {filename} ({size})"

    key_n = (
        len(key_ring)
        if use_http_only
        else (len(image_pool) if image_pool is not None else 1)
    )
    workers = max(
        1,
        min(
            concurrency
            if concurrency is not None
            else _default_image_concurrency(key_n),
            len(pending),
        ),
    )
    if workers == 1 or len(pending) == 1:
        for filename, alt in pending:
            msg = _one(filename, alt)
            if msg:
                warnings.append(msg)
        return warnings

    print(
        f"文生图并行：{len(pending)} 张，workers={workers}，keys={key_n}",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futs = [executor.submit(_one, fn, alt) for fn, alt in pending]
        for fut in as_completed(futs):
            msg = fut.result()
            if msg:
                warnings.append(msg)
    return warnings
