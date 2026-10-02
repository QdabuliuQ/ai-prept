#!/usr/bin/env node
/**
 * Convert a PPTX file → WebPPT html-slide template package via @aiden0z/pptx-renderer.
 * Used by the PPT Master pipeline (SVG → PPTX → template pack). Not a drafts drop-in tool.
 *
 * Usage:
 *   node backend/scripts/pptx-to-template-package.mjs --pptx <file.pptx> [options]
 *
 * Options:
 *   --out-root <dir>              default: <repo>/agent-output
 *   --pptx <file>                 required; PPTX to convert
 *   --template-id <id>            force output folder / template_id
 *   --preserve-source-data-attrs  keep renderer data-* (default: strip, keep data-slot*)
 *   --svg-inline-max-chars <n>    inline SVG longer than this → images/vectors/ (default 2500)
 *   --no-pending                  do not set status=pending (default pending when out-root is agent-output)
 *   --status <pending|draft|approved>
 *   --format <html-slide|ppt-master>  provenance in template.json (default html-slide)
 *   --complex-as-image            rasterize chart/table (default true)
 *   --no-complex-as-image
 *   --max-entry-mb <n>            ZIP 单文件上限 MiB（默认 256；含 wav/视频）
 *   --max-media-mb <n>            ppt/media 总量上限 MiB（默认 768）
 *   --max-total-mb <n>            解压总量上限 MiB（默认 1024）
 *
 * Package layout mirrors existing templates:
 *   agent-output/<id>/{template.json,theme.css,slides/*.html,images/}
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import http from "node:http";

import {
  classifyLayout,
  uniquifyLayouts,
  describeLayout,
  flattenNodes,
} from "./lib/pptx-convert/layout.mjs";
import { slotAttrsForNode, guessSlideTitle } from "./lib/pptx-convert/slots.mjs";
import { postprocessSlideHtml } from "./lib/pptx-convert/postprocess.mjs";
import {
  applyPictureClips,
  loadPictureClipsBySlide,
} from "./lib/pptx-convert/picture-clip.mjs";
import {
  writeTemplatePackage,
  templateIdFromPptx,
} from "./lib/pptx-convert/package-write.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../..");
const CANVAS_W = 1920;
const CANVAS_H = 1080;
const COMPLEX_TYPES = new Set(["chart", "table"]);

const require = createRequire(import.meta.url);

function resolvePuppeteer() {
  const candidates = [
    path.resolve(process.cwd(), "node_modules/puppeteer"),
    path.resolve(REPO_ROOT, "node_modules/puppeteer"),
  ];
  for (const p of candidates) {
    try {
      return require(p);
    } catch {
      /* next */
    }
  }
  throw new Error("puppeteer not found. Install at repo root: npm i puppeteer");
}

function resolveRendererBrowser() {
  const candidates = [
    path.resolve(process.cwd(), "node_modules/@aiden0z/pptx-renderer/dist/aiden0z-pptx-renderer.browser.es.js"),
    path.resolve(REPO_ROOT, "node_modules/@aiden0z/pptx-renderer/dist/aiden0z-pptx-renderer.browser.es.js"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error(
    "@aiden0z/pptx-renderer not found. Install: npm i @aiden0z/pptx-renderer",
  );
}

function parseArgs(argv) {
  const args = {
    outRoot: path.join(REPO_ROOT, "agent-output"),
    pptx: null,
    templateId: null,
    preserveSourceDataAttrs: false,
    svgInlineMaxChars: 2500,
    status: null,
    format: "html-slide",
    complexAsImage: true,
    /** Trusted local files: loftier than RECOMMENDED_ZIP_LIMITS (32MiB/entry). */
    maxEntryMb: 256,
    maxMediaMb: 768,
    maxTotalMb: 1024,
  };
  const rest = [...argv];
  while (rest.length) {
    const a = rest.shift();
    if (a === "--out-root") args.outRoot = path.resolve(rest.shift());
    else if (a === "--pptx") args.pptx = path.resolve(rest.shift());
    else if (a === "--template-id") args.templateId = String(rest.shift()).trim();
    else if (a === "--preserve-source-data-attrs") args.preserveSourceDataAttrs = true;
    else if (a === "--svg-inline-max-chars")
      args.svgInlineMaxChars = Number(rest.shift()) || 2500;
    else if (a === "--no-pending") args.status = "draft";
    else if (a === "--status") args.status = String(rest.shift());
    else if (a === "--format") {
      const f = String(rest.shift() || "").trim();
      args.format = f === "ppt-master" ? "ppt-master" : "html-slide";
    }
    else if (a === "--complex-as-image") args.complexAsImage = true;
    else if (a === "--no-complex-as-image") args.complexAsImage = false;
    else if (a === "--max-entry-mb") args.maxEntryMb = Number(rest.shift()) || 256;
    else if (a === "--max-media-mb") args.maxMediaMb = Number(rest.shift()) || 768;
    else if (a === "--max-total-mb") args.maxTotalMb = Number(rest.shift()) || 1024;
    else if (a === "--help" || a === "-h") args.help = true;
    else throw new Error(`Unknown arg: ${a}`);
  }
  return args;
}

function zipLimitsFromArgs(args) {
  const MiB = 1024 * 1024;
  return {
    maxEntries: 8000,
    maxEntryUncompressedBytes: Math.max(64, args.maxEntryMb) * MiB,
    maxTotalUncompressedBytes: Math.max(128, args.maxTotalMb) * MiB,
    maxMediaBytes: Math.max(64, args.maxMediaMb) * MiB,
    maxConcurrency: 8,
  };
}

function resolvePptxFile(pptx) {
  if (!pptx) {
    throw new Error("Missing required --pptx <file.pptx>");
  }
  if (!fs.existsSync(pptx)) throw new Error(`PPTX not found: ${pptx}`);
  return pptx;
}

function defaultStatus(outRoot, explicit) {
  if (explicit) return explicit;
  const norm = path.resolve(outRoot);
  const agentOut = path.resolve(REPO_ROOT, "agent-output");
  return norm === agentOut || norm.startsWith(agentOut + path.sep)
    ? "pending"
    : "draft";
}

/** Tiny static server so Chromium can ESM-import the renderer bundle. */
function startStaticServer(rootDir) {
  const server = http.createServer((req, res) => {
    try {
      const urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
      const rel = urlPath === "/" ? "/index.html" : urlPath;
      const abs = path.normalize(path.join(rootDir, rel));
      if (!abs.startsWith(rootDir)) {
        res.writeHead(403);
        res.end("forbidden");
        return;
      }
      if (!fs.existsSync(abs) || fs.statSync(abs).isDirectory()) {
        res.writeHead(404);
        res.end("missing");
        return;
      }
      const ext = path.extname(abs).toLowerCase();
      const types = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      };
      res.writeHead(200, { "Content-Type": types[ext] || "application/octet-stream" });
      fs.createReadStream(abs).pipe(res);
    } catch (e) {
      res.writeHead(500);
      res.end(String(e));
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, port, baseUrl: `http://127.0.0.1:${port}` });
    });
  });
}

function writeHarness(tmpDir, rendererRelUrl) {
  const html = `<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><title>pptx-convert</title></head>
<body>
  <div id="mount"></div>
  <script type="module">
    import {
      parseZip,
      buildPresentation,
      renderSlide,
      serializePresentation,
      RECOMMENDED_ZIP_LIMITS,
    } from "${rendererRelUrl}";

    /** Local draft conversion: raised vs RECOMMENDED (32MiB/entry). Overridden by load(buffer, limits). */
    const DEFAULT_CONVERT_ZIP_LIMITS = {
      maxEntries: 8000,
      maxEntryUncompressedBytes: 256 * 1024 * 1024,
      maxTotalUncompressedBytes: 1024 * 1024 * 1024,
      maxMediaBytes: 768 * 1024 * 1024,
      maxConcurrency: 8,
    };

    function flatten(nodes, out = []) {
      for (const n of nodes || []) {
        out.push(n);
        if (n.children?.length) flatten(n.children, out);
      }
      return out;
    }

    function approxMatch(el, node, scaleX, scaleY) {
      const st = el.style;
      const left = parseFloat(st.left) || 0;
      const top = parseFloat(st.top) || 0;
      const w = parseFloat(st.width) || el.offsetWidth || 0;
      const h = parseFloat(st.height) || el.offsetHeight || 0;
      const nx = (node.position?.x || 0) * scaleX;
      const ny = (node.position?.y || 0) * scaleY;
      const nw = (node.size?.w || 0) * scaleX;
      const nh = (node.size?.h || 0) * scaleY;
      const tol = 6;
      return (
        Math.abs(left - nx) <= tol &&
        Math.abs(top - ny) <= tol &&
        (nw < 4 || Math.abs(w - nw) <= Math.max(tol, nw * 0.08)) &&
        (nh < 4 || Math.abs(h - nh) <= Math.max(tol, nh * 0.08))
      );
    }

    function applyAttrs(el, attrs) {
      if (!el || !attrs) return;
      for (const [k, v] of Object.entries(attrs)) {
        if (v != null && v !== "") el.setAttribute(k, String(v));
      }
    }

    function plainText(el) {
      return String(el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
    }

    function maxFontPt(el) {
      let best = null;
      const nodes = [el, ...el.querySelectorAll("*")];
      for (const n of nodes) {
        const st = n.getAttribute?.("style") || n.style?.cssText || "";
        const m = st.match(/font-size\\s*:\\s*([\\d.]+)\\s*pt/i);
        if (m) best = Math.max(best || 0, parseFloat(m[1]));
      }
      return best;
    }

    function inferTextRole(text, fontPt) {
      const n = text.length;
      if (fontPt != null) {
        if (fontPt >= 40 && n <= 60) return "heading";
        if (fontPt >= 28 && n <= 100) return "lede";
      }
      if (n <= 24) return "meta";
      if (n <= 80) return "heading";
      return "body";
    }

    /** Tag absolute text boxes that plan matching missed (prefer outermost). */
    function tagOrphanTextSlots(root) {
      const cands = [...root.querySelectorAll("div")].filter((el) => {
        if (el.hasAttribute("data-slot") || el.closest("[data-slot]")) return false;
        if (el.querySelector("[data-slot]")) return false;
        const pos = el.style?.position || "";
        if (pos !== "absolute") return false;
        if (!el.querySelector("span")) return false;
        return plainText(el).length >= 1;
      });
      const outers = cands.filter(
        (el) => !cands.some((other) => other !== el && other.contains(el)),
      );
      let textI = root.querySelectorAll("[data-slot-type='text']").length;
      for (const el of outers) {
        const text = plainText(el);
        const fontPt = maxFontPt(el);
        const role = inferTextRole(text, fontPt);
        let slot;
        if (role === "heading" || role === "page-title") {
          slot = textI === 0 ? "title" : \`title-\${textI + 1}\`;
        } else if (role === "lede") {
          slot = textI === 0 ? "subtitle" : \`subtitle-\${textI + 1}\`;
        } else if (role === "meta") {
          slot = textI === 0 ? "eyebrow" : \`eyebrow-\${textI + 1}\`;
        } else {
          slot = \`body-\${textI + 1}\`;
        }
        applyAttrs(el, {
          "data-slot": slot,
          "data-slot-type": "text",
          "data-slot-role": role === "heading" && textI === 0 ? "page-title" : role,
        });
        textI += 1;
      }
    }

    function parseRotateDeg(transform) {
      const t = String(transform || "");
      const m = t.match(/rotate\\(\\s*(-?[\\d.]+)\\s*deg\\s*\\)/i);
      return m ? Number(m[1]) : null;
    }

    /** Annotate rotate/flip; keep CSS transform on the wrapper (overflow:hidden + rotate must stay together). */
    function promoteMediaTransforms(root) {
      root.querySelectorAll("*").forEach((el) => {
        const tf = el.style?.transform || "";
        if (!/rotate\\(|scaleX\\(|scaleY\\(/i.test(tf)) return;
        el.style.transformOrigin = el.style.transformOrigin || "center center";
        const deg = parseRotateDeg(tf);
        if (deg != null && Math.abs(deg) >= 0.5) {
          el.setAttribute("data-rotate", String(Number(deg.toFixed(4))));
        }
      });

      // Mirror data-rotate onto nested <img> for WebPPT / export parsers that start at the media node.
      root.querySelectorAll("img").forEach((img) => {
        if (img.getAttribute("data-rotate")) return;
        let host = img.parentElement;
        for (let d = 0; d < 6 && host && host !== root; d++) {
          const deg =
            parseRotateDeg(host.style.transform) ??
            (host.getAttribute("data-rotate")
              ? Number(host.getAttribute("data-rotate"))
              : null);
          if (deg != null && Math.abs(deg) >= 0.5) {
            img.setAttribute("data-rotate", String(Number(deg.toFixed(4))));
            break;
          }
          host = host.parentElement;
        }
      });
    }

    function applyNodeTransform(el, plan) {
      if (!el || !plan) return;
      const rot = Number(plan.rotation) || 0;
      const parts = [];
      if (Math.abs(rot) >= 0.05) parts.push(\`rotate(\${rot}deg)\`);
      if (plan.flipH) parts.push("scaleX(-1)");
      if (plan.flipV) parts.push("scaleY(-1)");
      if (!parts.length) return;
      const existing = String(el.style.transform || "").trim();
      if (!existing || existing === "none") {
        el.style.transform = parts.join(" ");
      } else if (!/rotate\\(/i.test(existing) && Math.abs(rot) >= 0.05) {
        el.style.transform = \`\${existing} \${parts.join(" ")}\`.trim();
      }
      el.style.transformOrigin = "center center";
      if (Math.abs(rot) >= 0.05) {
        el.setAttribute("data-rotate", String(Number(rot.toFixed(4))));
      }
    }

    window.__pptxConvert = {
      async load(buffer, limits) {
        const zipLimits = { ...RECOMMENDED_ZIP_LIMITS, ...DEFAULT_CONVERT_ZIP_LIMITS, ...(limits || {}) };
        const files = await parseZip(buffer, zipLimits);
        const presentation = buildPresentation(files);
        const serialized = serializePresentation(presentation);
        this._presentation = presentation;
        this._serialized = serialized;
        this._handles = [];
        return {
          width: presentation.width,
          height: presentation.height,
          slideCount: presentation.slides.length,
          slides: serialized.slides,
        };
      },

      async renderAnnotated(index, slotPlan) {
        const presentation = this._presentation;
        const slide = presentation.slides[index];
        const mount = document.getElementById("mount");
        mount.innerHTML = "";
        for (const h of this._handles) {
          try { h.dispose(); } catch { /* */ }
        }
        this._handles = [];

        const handle = renderSlide(presentation, slide, {});
        this._handles.push(handle);
        mount.appendChild(handle.element);
        await handle.ready;
        // charts / fonts
        await new Promise((r) => setTimeout(r, 120));
        if (document.fonts?.ready) {
          try { await document.fonts.ready; } catch { /* */ }
        }

        const root = handle.element;
        root.classList.add("pptx-slide-root");
        root.style.position = "relative";
        root.style.overflow = "hidden";

        const ser = this._serialized.slides[index];
        const flat = flatten(ser.nodes);
        const candidates = [...root.querySelectorAll(":scope > *")];

        const used = new Set();
        for (const plan of slotPlan || []) {
          const node = flat.find((n) => n.id === plan.nodeId) || flat[plan.flatIndex];
          if (!node) continue;
          let el = candidates.find((c, i) => !used.has(i) && approxMatch(c, node, 1, 1));
          if (!el) {
            // deeper search for nested pictures/charts
            el = [...root.querySelectorAll("*")].find((c) => {
              if (c === root) return false;
              return approxMatch(c, node, 1, 1);
            });
          }
          if (!el) continue;
          const ci = candidates.indexOf(el);
          if (ci >= 0) used.add(ci);
          applyAttrs(el, plan.attrs);
          el.setAttribute("data-pptx-node-type", node.nodeType || "");
          el.setAttribute("data-pptx-node-id", node.id || "");
          applyNodeTransform(el, plan);
          if (plan.complex) {
            el.setAttribute("data-pptx-complex", "1");
            el.setAttribute("data-pptx-complex-name", plan.assetStem || "complex");
          }
        }

        // Heuristic: bare <img> without slot
        let imgI = 0;
        for (const img of root.querySelectorAll("img")) {
          if (img.hasAttribute("data-slot")) continue;
          if (img.closest("[data-slot]")) continue;
          imgI += 1;
          applyAttrs(img, {
            "data-slot": \`image-\${imgI}\`,
            "data-slot-type": "image",
            "data-slot-role": imgI === 1 ? "hero-image" : "image",
          });
        }

        // Fallback: nested absolute text boxes missed by coordinate match
        tagOrphanTextSlots(root);

        return {
          width: presentation.width,
          height: presentation.height,
          complexSelectors: [...root.querySelectorAll("[data-pptx-complex='1']")].map((el, i) => ({
            index: i,
            name: el.getAttribute("data-pptx-complex-name") || \`complex-\${i + 1}\`,
          })),
        };
      },

      async replaceComplexWithImages(replacements) {
        const root = document.querySelector("#mount .pptx-slide-root");
        if (!root) return;
        const nodes = [...root.querySelectorAll("[data-pptx-complex='1']")];
        for (const rep of replacements) {
          const el = nodes[rep.index];
          if (!el) continue;
          const img = document.createElement("img");
          img.src = rep.src;
          img.alt = rep.alt || "";
          img.setAttribute("data-slot", rep.slot || el.getAttribute("data-slot") || \`complex-\${rep.index + 1}\`);
          img.setAttribute("data-slot-type", rep.slotType || "image");
          img.setAttribute("data-slot-role", rep.slotRole || "chart");
          img.style.cssText = el.style.cssText || "";
          if (!img.style.position) img.style.position = "absolute";
          if (!img.style.left) img.style.left = el.style.left || "0px";
          if (!img.style.top) img.style.top = el.style.top || "0px";
          if (!img.style.width) img.style.width = el.style.width || \`\${el.offsetWidth}px\`;
          if (!img.style.height) img.style.height = el.style.height || \`\${el.offsetHeight}px\`;
          img.style.objectFit = "contain";
          el.replaceWith(img);
        }
      },

      exportScaledHtml(layout) {
        const root = document.querySelector("#mount .pptx-slide-root");
        if (!root) return "";
        promoteMediaTransforms(root);
        const w = parseFloat(root.style.width) || root.offsetWidth || ${CANVAS_W};
        const h = parseFloat(root.style.height) || root.offsetHeight || ${CANVAS_H};
        const scale = Math.min(${CANVAS_W} / w, ${CANVAS_H} / h);
        const clone = root.cloneNode(true);
        clone.querySelectorAll("[data-pptx-complex]").forEach((el) => {
          el.removeAttribute("data-pptx-complex");
          el.removeAttribute("data-pptx-complex-name");
        });

        const scaleCss = (css, k) =>
          String(css || "").replace(/(-?[\\d.]+)(px|pt)\\b/gi, (_, n, u) => {
            const x = parseFloat(n) * k;
            return \`\${Number(x.toFixed(4))}\${u}\`;
          });
        const flatten = (el, k) => {
          if (!el || el.nodeType !== 1) return;
          if (el.style && el.style.cssText) {
            el.style.cssText = scaleCss(el.style.cssText, k);
          }
          const tag = (el.tagName || "").toLowerCase();
          if (tag === "svg") {
            for (const a of ["width", "height", "x", "y"]) {
              const v = el.getAttribute(a);
              if (v && /^-?[\\d.]+(px)?$/.test(String(v).trim())) {
                el.setAttribute(a, String(Number((parseFloat(v) * k).toFixed(4))));
              }
            }
          }
          for (const c of el.children || []) flatten(c, k);
        };
        if (Math.abs(scale - 1) > 0.001) flatten(clone, scale);

        clone.classList.add("slide", "slide-container", \`layout-\${layout}\`);
        clone.style.position = "relative";
        clone.style.overflow = "hidden";
        clone.style.width = "${CANVAS_W}px";
        clone.style.height = "${CANVAS_H}px";
        const bg = clone.style.backgroundColor || "#fff";
        clone.style.background = bg;
        return clone.outerHTML;
      },

      dispose() {
        for (const h of this._handles || []) {
          try { h.dispose(); } catch { /* */ }
        }
        this._handles = [];
        const mount = document.getElementById("mount");
        if (mount) mount.innerHTML = "";
      },
    };

    window.__pptxReady = true;
  </script>
</body>
</html>`;
  fs.writeFileSync(path.join(tmpDir, "index.html"), html, "utf8");
}

function buildSlotPlan(serializedSlide, complexAsImage) {
  const flat = flattenNodes(serializedSlide.nodes || []);
  const plan = [];
  let textI = 0;
  let imageI = 0;
  let chartI = 0;
  let tableI = 0;

  for (let i = 0; i < flat.length; i++) {
    const node = flat[i];
    const text = node.textBody?.totalText || "";
    let counterCtx = { index: 0 };
    if (node.nodeType === "picture") {
      counterCtx.index = imageI++;
    } else if (node.nodeType === "chart") {
      counterCtx.index = chartI++;
    } else if (node.nodeType === "table") {
      counterCtx.index = tableI++;
    } else if (node.nodeType === "shape" && text.trim()) {
      counterCtx.index = textI++;
    } else {
      continue;
    }

    const attrs = slotAttrsForNode(node.nodeType, {
      name: node.name,
      text,
      index: counterCtx.index,
    });
    if (!attrs) continue;

    const complex =
      complexAsImage && COMPLEX_TYPES.has(node.nodeType);
    plan.push({
      nodeId: node.id,
      flatIndex: i,
      attrs,
      complex,
      assetStem:
        node.nodeType === "chart"
          ? `chart-${chartI}`
          : node.nodeType === "table"
            ? `table-${tableI}`
            : null,
      slotType: attrs["data-slot-type"],
      slotRole: attrs["data-slot-role"],
      slot: attrs["data-slot"],
      rotation: Number(node.rotation) || 0,
      flipH: Boolean(node.flipH),
      flipV: Boolean(node.flipV),
    });
  }
  return plan;
}

async function convertOnePptx(browser, baseUrl, pptxPath, args, serveRoot) {
  const warnings = [];
  const templateId =
    args.templateId || templateIdFromPptx(path.basename(pptxPath));
  const outDir = path.join(args.outRoot, templateId);
  /** 重转同一 id 时保留 visual-spec / 审核元数据，避免准备上传再被「缺设计规范」拦住 */
  let preservedSpec = null;
  let preservedMeta = null;

  // Stage PPTX first: in-place --pptx agent-output/<id>/source.pptx would vanish
  // if we rmSync(outDir) before copying.
  const pptxServeName = `input-${cryptoRandom()}.pptx`;
  const stagedPptx = path.join(serveRoot, pptxServeName);
  fs.copyFileSync(pptxPath, stagedPptx);
  const resolvedSource = stagedPptx;

  if (fs.existsSync(outDir)) {
    const specPath = path.join(outDir, "visual-spec.md");
    try {
      if (fs.existsSync(specPath)) {
        const text = fs.readFileSync(specPath, "utf8");
        if (text.trim()) preservedSpec = text;
      }
    } catch {
      /* ignore */
    }
    try {
      const metaPath = path.join(outDir, "template.json");
      if (fs.existsSync(metaPath)) {
        preservedMeta = JSON.parse(fs.readFileSync(metaPath, "utf8"));
      }
    } catch {
      /* ignore */
    }
    fs.rmSync(outDir, { recursive: true, force: true });
  }
  fs.mkdirSync(path.join(outDir, "images"), { recursive: true });
  fs.mkdirSync(path.join(outDir, "slides"), { recursive: true });
  // Keep a local source.pptx so Admin can re-convert / browser-convert later.
  fs.copyFileSync(resolvedSource, path.join(outDir, "source.pptx"));

  const page = await browser.newPage();
  await page.setViewport({
    width: CANVAS_W,
    height: CANVAS_H,
    deviceScaleFactor: 2,
  });
  await page.goto(`${baseUrl}/index.html`, {
    waitUntil: "networkidle0",
    timeout: 60_000,
  });
  await page.waitForFunction(() => window.__pptxReady === true, {
    timeout: 30_000,
  });

  const zipLimits = zipLimitsFromArgs(args);
  const pictureClipsBySlide = await loadPictureClipsBySlide(resolvedSource);
  const meta = await page.evaluate(
    async (pptxUrl, limits) => {
      const res = await fetch(pptxUrl);
      if (!res.ok) throw new Error(`fetch pptx failed: ${res.status}`);
      const buffer = await res.arrayBuffer();
      return window.__pptxConvert.load(buffer, limits);
    },
    `${baseUrl}/${pptxServeName}`,
    zipLimits,
  );

  const bases = [];
  const classified = [];
  for (let i = 0; i < meta.slideCount; i++) {
    const slideSer = meta.slides[i];
    const c = classifyLayout({
      nodes: slideSer.nodes,
      index: i,
      slideCount: meta.slideCount,
      slideW: meta.width,
      slideH: meta.height,
    });
    bases.push(c.base);
    classified.push(c);
  }
  const layouts = uniquifyLayouts(bases);

  const slidesOut = [];
  for (let i = 0; i < meta.slideCount; i++) {
    const layout = layouts[i];
    const slideSer = meta.slides[i];
    const title = guessSlideTitle(slideSer.nodes);
    const plan = buildSlotPlan(slideSer, args.complexAsImage);

    const info = await page.evaluate(
      async (index, slotPlan) => window.__pptxConvert.renderAnnotated(index, slotPlan),
      i,
      plan,
    );

    // Rasterize complex nodes
    if (args.complexAsImage && info.complexSelectors?.length) {
      const handles = await page.$$(
        `#mount .pptx-slide-root [data-pptx-complex='1']`,
      );
      const replacements = [];
      for (const item of info.complexSelectors) {
        const el = handles[item.index];
        if (!el) continue;
        const file = `${layout}-${item.name}.png`;
        const abs = path.join(outDir, "images", file);
        try {
          await el.screenshot({ path: abs, type: "png" });
          const planItem = plan.find((p) => p.assetStem === item.name) || {};
          replacements.push({
            index: item.index,
            src: `../images/${file}`,
            alt: title,
            slot: planItem.slot,
            slotType: planItem.slotType === "chart" ? "chart" : "image",
            slotRole: planItem.slotRole || "chart",
          });
        } catch (e) {
          warnings.push(
            `${layout}: complex screenshot failed (${item.name}): ${e.message || e}`,
          );
        }
      }
      if (replacements.length) {
        await page.evaluate(
          (reps) => window.__pptxConvert.replaceComplexWithImages(reps),
          replacements,
        );
      }
    }

    // Materialize blob:/data: images into images/ (HTML <img> + SVG <image>)
    const ephemeral = await page.evaluate(() => {
      const root = document.querySelector("#mount .pptx-slide-root");
      if (!root) return [];
      const out = [];
      root.querySelectorAll("img").forEach((img, idx) => {
        const src = img.getAttribute("src") || "";
        if (src.startsWith("blob:") || src.startsWith("data:")) {
          out.push({ kind: "img", idx, src });
        }
      });
      root.querySelectorAll("image").forEach((el, idx) => {
        const src =
          el.getAttribute("href") ||
          el.getAttribute("xlink:href") ||
          el.getAttributeNS?.("http://www.w3.org/1999/xlink", "href") ||
          "";
        if (src.startsWith("blob:") || src.startsWith("data:")) {
          out.push({ kind: "svg-image", idx, src });
        }
      });
      return out;
    });

    let assetI = 0;
    for (const item of ephemeral) {
      try {
        const result = await page.evaluate(async (src) => {
          if (String(src).startsWith("data:")) {
            const m = String(src).match(/^data:([^;]+);base64,(.+)$/);
            if (m) return { mime: m[1], b64: m[2] };
            return { mime: "image/png", b64: String(src) };
          }
          const res = await fetch(src);
          const blob = await res.blob();
          const ab = await blob.arrayBuffer();
          const bytes = new Uint8Array(ab);
          let binary = "";
          const chunk = 0x8000;
          for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
          }
          return {
            mime: blob.type || "image/png",
            b64: btoa(binary),
          };
        }, item.src);
        const ext = /jpeg|jpg/i.test(result.mime)
          ? "jpg"
          : /webp/i.test(result.mime)
            ? "webp"
            : /svg/i.test(result.mime)
              ? "svg"
              : "png";
        assetI += 1;
        const file = `${layout}-asset-${assetI}.${ext}`;
        fs.writeFileSync(
          path.join(outDir, "images", file),
          Buffer.from(result.b64, "base64"),
        );
        await page.evaluate(
          (kind, idx, nextSrc) => {
            const root = document.querySelector("#mount .pptx-slide-root");
            if (!root) return;
            if (kind === "img") {
              const img = root.querySelectorAll("img")[idx];
              if (img) img.setAttribute("src", nextSrc);
              return;
            }
            const el = root.querySelectorAll("image")[idx];
            if (!el) return;
            el.setAttribute("href", nextSrc);
            el.setAttribute("xlink:href", nextSrc);
            try {
              el.setAttributeNS("http://www.w3.org/1999/xlink", "href", nextSrc);
            } catch {
              /* ignore */
            }
          },
          item.kind,
          item.idx,
          `../images/${file}`,
        );
      } catch (e) {
        warnings.push(
          `${layout}: materialize ${item.kind}#${item.idx} failed: ${e.message || e}`,
        );
      }
    }

    // SVG <image> often blanks in preview/snapdom — promote to HTML <img>
    const promoted = await page.evaluate(() => {
      const root = document.querySelector("#mount .pptx-slide-root");
      if (!root) return 0;
      const XLINK = "http://www.w3.org/1999/xlink";
      const getHref = (el) =>
        el.getAttribute("href") ||
        el.getAttribute("xlink:href") ||
        (el.getAttributeNS && el.getAttributeNS(XLINK, "href")) ||
        "";
      const radiusFromClip = (clipEl, vbW, vbH) => {
        if (!clipEl || !(vbW > 0) || !(vbH > 0)) return "";
        const shape =
          clipEl.querySelector("circle, ellipse, path") ||
          clipEl.firstElementChild;
        if (!shape) return "";
        const tag = shape.tagName.toLowerCase();
        if (tag === "circle" || tag === "ellipse") return "50%";
        const d = shape.getAttribute("d") || "";
        const arcs = [...d.matchAll(/A\s*([\d.]+)\s*,\s*([\d.]+)/gi)];
        if (
          arcs.length >= 2 &&
          Math.abs(Number(arcs[0][1]) - Number(arcs[0][2])) < 0.5
        ) {
          const r = Number(arcs[0][1]);
          if (Math.abs(r * 2 - Math.min(vbW, vbH)) < Math.max(2, vbW * 0.02)) {
            return "50%";
          }
        }
        if (arcs.length >= 1) {
          const rx = Number(arcs[0][1]);
          const ry = Number(arcs[0][2]);
          if (Number.isFinite(rx) && Number.isFinite(ry) && rx > 0 && ry > 0) {
            return `${((rx / vbW) * 100).toFixed(2)}% / ${((ry / vbH) * 100).toFixed(2)}%`;
          }
        }
        return "";
      };

      let count = 0;
      for (const imageEl of [...root.querySelectorAll("image")]) {
        const href = getHref(imageEl);
        if (!href || href.startsWith("blob:") || href.startsWith("data:")) continue;
        const svg = imageEl.closest("svg");
        if (!svg) continue;
        const vb = String(svg.getAttribute("viewBox") || "")
          .trim()
          .split(/[\s,]+/)
          .map(Number);
        const vbW = vb[2] || 0;
        const vbH = vb[3] || 0;
        const clipped =
          imageEl.closest("[clip-path]") ||
          (imageEl.getAttribute("clip-path") ? imageEl : null);
        const clipRef =
          (clipped && clipped.getAttribute("clip-path")) ||
          imageEl.getAttribute("clip-path") ||
          "";
        const idMatch = clipRef.match(/url\(\s*#([^)\s]+)\s*\)/i);
        let clipEl = null;
        if (idMatch) {
          const id = idMatch[1];
          clipEl =
            svg.querySelector(`clipPath#${CSS.escape(id)}`) ||
            root.querySelector(`clipPath#${CSS.escape(id)}`);
        }
        const radius = radiusFromClip(clipEl, vbW, vbH);
        const host = svg.parentElement;
        const img = document.createElement("img");
        img.src = href;
        img.alt = "";
        img.style.cssText =
          "width:100%;height:100%;object-fit:cover;display:block;border:0";
        const slotHost =
          (host && host.closest("[data-slot]")) || svg.closest("[data-slot]");
        if (slotHost) {
          for (const a of [
            "data-slot",
            "data-slot-type",
            "data-slot-role",
            "data-rotate",
          ]) {
            const v = slotHost.getAttribute(a);
            if (v) img.setAttribute(a, v);
          }
        }
        if (host && host !== root) {
          if (radius) host.style.borderRadius = radius;
          host.style.overflow = "hidden";
          svg.replaceWith(img);
        } else {
          if (radius) img.style.borderRadius = radius;
          svg.replaceWith(img);
        }
        count += 1;
      }
      return count;
    });
    if (promoted) {
      warnings.push(
        `${layout}: SVG <image> ×${promoted} → HTML <img>（预览/截图更稳）`,
      );
    }

    // Gradient text (background-clip:text) is fragile in the editor — rasterize to PNG.
    const gradCount = await page.evaluate(() => {
      const root = document.querySelector("#mount .pptx-slide-root");
      if (!root) return 0;
      const isGradText = (el) => {
        if (!el || el.nodeType !== 1) return false;
        const st = window.getComputedStyle(el);
        const styleAttr = el.getAttribute("style") || "";
        const hasGrad =
          /linear-gradient/i.test(st.backgroundImage || "") ||
          /linear-gradient/i.test(styleAttr);
        if (!hasGrad) return false;
        const clip =
          `${st.webkitBackgroundClip || ""} ${st.backgroundClip || ""}`.toLowerCase();
        const clipped =
          clip.includes("text") ||
          /background-clip\s*:\s*text/i.test(styleAttr) ||
          /-\s*webkit-background-clip\s*:\s*text/i.test(styleAttr) ||
          /background\s*:[^;]*\btext\b/i.test(styleAttr) ||
          ((st.color === "transparent" || st.color === "rgba(0, 0, 0, 0)") &&
            hasGrad);
        if (!clipped) return false;
        return (el.innerText || el.textContent || "").trim().length > 0;
      };
      const cands = [
        ...root.querySelectorAll("span, p, div, h1, h2, h3, h4, h5, h6"),
      ].filter(isGradText);
      const leaves = cands.filter(
        (el) => !cands.some((other) => other !== el && el.contains(other)),
      );
      leaves.forEach((el, i) => {
        el.setAttribute("data-pptx-gradient-text", "1");
        el.setAttribute("data-pptx-gradient-text-i", String(i));
      });
      return leaves.length;
    });

    if (gradCount > 0) {
      const handles = await page.$$(
        `#mount .pptx-slide-root [data-pptx-gradient-text='1']`,
      );
      const replacements = [];
      for (let gi = 0; gi < handles.length; gi++) {
        const el = handles[gi];
        const file = `${layout}-gradtext-${gi + 1}.png`;
        const abs = path.join(outDir, "images", file);
        try {
          await el.screenshot({
            path: abs,
            type: "png",
            omitBackground: true,
          });
          const box = await el.evaluate((node) => {
            const root = document.querySelector("#mount .pptx-slide-root");
            const rr = node.getBoundingClientRect();
            const br = root.getBoundingClientRect();
            const slotHost = node.closest("[data-slot]") || node;
            return {
              left: rr.left - br.left,
              top: rr.top - br.top,
              width: Math.max(1, rr.width),
              height: Math.max(1, rr.height),
              slot: slotHost.getAttribute("data-slot") || "",
              slotRole: slotHost.getAttribute("data-slot-role") || "heading",
              text: (node.innerText || node.textContent || "")
                .trim()
                .slice(0, 80),
            };
          });
          replacements.push({
            index: gi,
            src: `../images/${file}`,
            ...box,
          });
        } catch (e) {
          warnings.push(
            `${layout}: gradient-text screenshot failed (#${gi + 1}): ${
              e.message || e
            }`,
          );
        }
      }
      if (replacements.length) {
        await page.evaluate((reps) => {
          const root = document.querySelector("#mount .pptx-slide-root");
          if (!root) return;
          const cs = window.getComputedStyle(root);
          if (cs.position === "static") root.style.position = "relative";
          for (const rep of reps) {
            const el = root.querySelector(
              `[data-pptx-gradient-text-i="${rep.index}"]`,
            );
            if (!el) continue;
            const host = el.closest("[data-slot]") || el;
            const img = document.createElement("img");
            img.src = rep.src;
            img.alt = rep.text || "";
            img.setAttribute("data-element", "image");
            img.setAttribute("data-slot-type", "image");
            img.setAttribute("data-slot-role", rep.slotRole || "heading");
            if (rep.slot) img.setAttribute("data-slot", rep.slot);
            img.style.cssText = [
              "position:absolute",
              `left:${Number(rep.left.toFixed(2))}px`,
              `top:${Number(rep.top.toFixed(2))}px`,
              `width:${Number(rep.width.toFixed(2))}px`,
              `height:${Number(rep.height.toFixed(2))}px`,
              "object-fit:contain",
              "display:block",
              "border:0",
              "margin:0",
              "padding:0",
              "pointer-events:auto",
            ].join(";");
            root.appendChild(img);
            if (host && host !== root) host.remove();
            else el.remove();
          }
        }, replacements);
        warnings.push(`${layout}: 渐变字降级为图片 ×${replacements.length}`);
      }
    }

    let rawHtml = await page.evaluate(
      (layoutId) => window.__pptxConvert.exportScaledHtml(layoutId),
      layout,
    );

    const processed = postprocessSlideHtml({
      html: rawHtml,
      imagesDir: path.join(outDir, "images"),
      slideStem: layout,
      preserveSourceDataAttrs: args.preserveSourceDataAttrs,
      svgInlineMaxChars: args.svgInlineMaxChars,
    });
    const clipFix = applyPictureClips(
      processed.html,
      pictureClipsBySlide[i] || [],
    );
    if (clipFix.applied) {
      warnings.push(`${layout}: 补 picture clip-path ×${clipFix.applied}`);
    }
    warnings.push(...processed.warnings);

    slidesOut.push({
      file: `slides/${layout}.html`,
      title,
      layout,
      description: describeLayout(layout, classified[i].stats, title),
      html: clipFix.html,
    });
  }

  await page.evaluate(() => window.__pptxConvert.dispose());
  await page.close();
  try {
    fs.unlinkSync(path.join(serveRoot, pptxServeName));
  } catch {
    /* ignore */
  }

  const relSource = `agent-output/${templateId}/source.pptx`;
  const status = defaultStatus(args.outRoot, args.status);
  const written = writeTemplatePackage({
    outDir,
    templateId,
    sourceFile: relSource,
    labelZh:
      (preservedMeta?.label && preservedMeta.label.zh_CN) ||
      path.basename(pptxPath, path.extname(pptxPath)),
    labelEn:
      (preservedMeta?.label && preservedMeta.label.en_US) ||
      path.basename(pptxPath, path.extname(pptxPath)),
    slides: slidesOut,
    warnings: [
      `pptx-renderer → html-slide；画布缩放 ${meta.width}×${meta.height} → ${CANVAS_W}×${CANVAS_H}`,
      ...warnings,
    ],
    status:
      preservedMeta?.status === "approved" ? "approved" : status,
    format: args.format,
  });

  // 合并保留字段（public_id / category / storage / preview / usage …）
  if (preservedMeta && typeof preservedMeta === "object") {
    try {
      const metaPath = path.join(outDir, "template.json");
      const next = {
        ...written,
        public_id: preservedMeta.public_id || written.public_id,
        category: preservedMeta.category || written.category,
        usage: preservedMeta.usage || written.usage,
        storage: preservedMeta.storage || written.storage,
        preview: preservedMeta.preview || written.preview,
        featured: preservedMeta.featured,
      };
      if (preservedMeta.status === "approved") next.status = "approved";
      fs.writeFileSync(metaPath, JSON.stringify(next, null, 2) + "\n", "utf8");
    } catch {
      /* ignore */
    }
  }
  if (preservedSpec) {
    fs.writeFileSync(path.join(outDir, "visual-spec.md"), preservedSpec.endsWith("\n") ? preservedSpec : preservedSpec + "\n", "utf8");
  }

  return {
    templateId,
    outDir,
    slideCount: slidesOut.length,
    status: preservedMeta?.status === "approved" ? "approved" : status,
  };
}

function cryptoRandom() {
  return Math.random().toString(16).slice(2, 10);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(`Usage: node backend/scripts/pptx-to-template-package.mjs --pptx <file.pptx> [options]
See file header for options.`);
    return;
  }

  let pptx;
  try {
    pptx = resolvePptxFile(args.pptx);
  } catch (e) {
    console.error(e instanceof Error ? e.message : String(e));
    process.exitCode = 1;
    return;
  }

  fs.mkdirSync(args.outRoot, { recursive: true });

  const rendererAbs = resolveRendererBrowser();
  const tmpDir = fs.mkdtempSync(path.join(REPO_ROOT, "agent-output", ".pptx-convert-"));
  // Serve repo-ish tree: harness + node_modules renderer via copied/symlink path
  const serveRoot = tmpDir;
  const nmLink = path.join(serveRoot, "vendor");
  fs.mkdirSync(nmLink, { recursive: true });
  fs.copyFileSync(
    rendererAbs,
    path.join(nmLink, "pptx-renderer.browser.es.js"),
  );
  writeHarness(serveRoot, "./vendor/pptx-renderer.browser.es.js");

  const { server, baseUrl } = await startStaticServer(serveRoot);
  let browser;
  try {
    const puppeteer = resolvePuppeteer();
    browser = await puppeteer.launch({
      headless: true,
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  } catch (e) {
    server.close();
    fs.rmSync(tmpDir, { recursive: true, force: true });
    throw e;
  }

  const results = [];
  const errors = [];
  try {
    console.log(`Converting ${pptx} …`);
    try {
      const r = await convertOnePptx(browser, baseUrl, pptx, args, serveRoot);
      results.push(r);
      console.log(
        `  → ${r.outDir} (${r.slideCount} slides, status=${r.status})`,
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      errors.push({ pptx, error: msg });
      console.error(`  ✗ ${path.basename(pptx)}: ${msg}`);
    }
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {
        /* ignore */
      }
    }
    server.close();
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }

  console.log(JSON.stringify({ ok: errors.length === 0, results, errors }, null, 2));
  if (errors.length) process.exitCode = 1;
}

main().catch((err) => {
  console.error(err instanceof Error ? err.stack || err.message : String(err));
  process.exit(1);
});
