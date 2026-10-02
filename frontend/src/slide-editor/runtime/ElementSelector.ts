/**
 * Element Selector
 * Handles element selection and highlighting
 */

import type { EditorBridge } from "./core/EditorBridge";
import {
  ensureEditorId,
  findElement,
  getElementSelector,
  isInjectedElement,
  rememberEditorElement,
  resolveEditableHost,
  type EditableElement,
} from "./utils/dom";
import { normalizeColor, normalizeTextAlign } from "./utils/css";
import {
	isSlideShellElement,
	getUnrotatedViewportBox,
	prepareElementForEditorTransform,
	releaseAncestorOverflow,
	releaseAllTextSlotOverflow,
} from "./utils/transform";

const TEXT_EDITING_STYLE_ID = "magic-editor-text-editing-style"

interface ElementInfo {
	selector: string
	editorId?: string
	tagName: string
	isImageElement?: boolean
	intrinsicWidth?: number
	intrinsicHeight?: number
	intrinsicAspectRatio?: number
	computedStyles: Record<string, string>
	rect: {
		top: number
		left: number
		width: number
		height: number
	}
	rotation?: number
	isTextElement?: boolean
	textContent?: string
	dataSlot?: string
	dataSlotType?: string
	dataSlotRole?: string
	dataElement?: string
	imageSrc?: string
}

function readElementMeta(element: EditableElement): {
	dataSlot?: string
	dataSlotType?: string
	dataSlotRole?: string
	dataElement?: string
	imageSrc?: string
} {
	const attr = (name: string) => {
		const v = element.getAttribute(name)?.trim()
		return v || undefined
	}
	let imageSrc = attr("src")
	if (!imageSrc) {
		const img = element.querySelector?.("img")
		imageSrc = img?.getAttribute("src")?.trim() || undefined
	}
	return {
		dataSlot: attr("data-slot"),
		dataSlotType: attr("data-slot-type"),
		dataSlotRole: attr("data-slot-role"),
		dataElement: attr("data-element"),
		imageSrc,
	}
}

export class ElementSelector {
	private selectedElements: Set<EditableElement> = new Set()
	private hoveredElement: EditableElement | null = null
	private enabled = false
	private bridge: EditorBridge
	private updateTimer: number | null = null
	private scrollCleanup: (() => void) | null = null
	private onTextEditingRequest?: (selector: string) => void
	private injectedTextEditingStyle: HTMLStyleElement | null = null

	constructor(bridge: EditorBridge) {
		this.bridge = bridge
		this.injectStyles()
		this.bindEvents()
		this.bindScrollListener()
		// 父级 overflow:hidden 会裁切字形；原先只在拖拽时 release，导致「拖一下才显示全」
		releaseAllTextSlotOverflow()
	}

	/**
	 * Set callback for text editing requests
	 */
	setTextEditingCallback(callback: (selector: string) => void): void {
		this.onTextEditingRequest = callback
	}

	/**
	 * Check if element is selected
	 */
	isSelected(element: EditableElement): boolean {
		return this.selectedElements.has(element)
	}

	/**
	 * Add element to selection
	 */
	addToSelection(element: EditableElement): void {
		this.selectedElements.add(element)
		this.notifySelectionChanged()
	}

	/**
	 * Remove element from selection
	 */
	removeFromSelection(element: EditableElement): void {
		// Remove editor-owned DOM state without changing author inline styles.
		if (element instanceof HTMLElement && element.getAttribute("data-text-editing") === "true") {
			element.contentEditable = "false"
			element.removeAttribute("data-text-editing")
		}
		this.selectedElements.delete(element)
		this.notifySelectionChanged()
	}

	/**
	 * Get all selected elements info
	 */
	getSelectedElementsInfo(): ElementInfo[] {
		const infos: ElementInfo[] = []
		this.selectedElements.forEach((element) => {
			const editorId = rememberEditorElement(element)
			const selector = getElementSelector(element)
			const styles = this.getElementStyles(element)
			const { rect, rotation } = this.getElementRectWithRotation(element)
			const isText = this.isTextElement(element)
			const textContent = element.textContent?.trim() || ""
			const imageMetadata = this.getImageMetadata(element)

			infos.push({
				selector,
				editorId,
				tagName: element.tagName.toLowerCase(),
				...imageMetadata,
				...readElementMeta(element),
				computedStyles: styles,
				rect,
				rotation,
				isTextElement: isText,
				textContent: isText ? textContent : undefined,
			})
		})
		return infos
	}

	/**
	 * Get selectors of all selected elements
	 */
	getSelectedSelectors(): string[] {
		const selectors: string[] = []
		this.selectedElements.forEach((element) => {
			selectors.push(getElementSelector(element))
		})
		return selectors
	}

	/**
	 * Get count of selected elements
	 */
	getSelectedCount(): number {
		return this.selectedElements.size
	}

	/**
	 * Refresh current selection info and notify parent
	 */
	refreshSelection(): void {
		this.notifySelectionChanged()
	}

	/**
	 * Apply text formatting to currently selected text element(s).
	 * Prefer an explicit parent target (selector/editorId) so formatting still
	 * works if iframe selection was lost; write onto the real text leaf so
	 * stylesheet rules on nested spans don't swallow the change.
	 */
	applyTextStyle(
		patch: {
			bold?: boolean | "toggle"
			italic?: boolean | "toggle"
			underline?: boolean | "toggle"
			strike?: boolean | "toggle"
			textAlign?: "left" | "center" | "right"
			color?: string
			fontSize?: number | "increase" | "decrease"
		},
		target?: { selector?: string; editorId?: string },
	): { success: boolean; applied: number } {
		const elements = new Set<HTMLElement>()

		if (target?.editorId || target?.selector) {
			const el = findElement(target.selector, target.editorId)
			if (el instanceof HTMLElement) elements.add(el)
		}
		for (const el of Array.from(this.selectedElements)) {
			if (el instanceof HTMLElement) elements.add(el)
		}

		let applied = 0
		for (const element of elements) {
			if (!this.canFormatElement(element)) continue
			this.writeTextStyle(element, patch)
			// Keep selection bookkeeping in sync when parent retargeted by id
			if (!this.selectedElements.has(element)) {
				ensureEditorId(element)
				rememberEditorElement(element)
				this.selectedElements.add(element)
			}
			applied += 1
		}

		if (applied > 0) {
			this.notifySelectionChanged()
		}
		return { success: applied > 0, applied }
	}

	private canFormatElement(element: HTMLElement): boolean {
		if (this.isTextElement(element)) return true
		const dataElement = (
			element.getAttribute("data-element") || ""
		).toLowerCase()
		if (
			dataElement === "image" ||
			dataElement === "shape" ||
			dataElement === "chart"
		) {
			return false
		}
		return (element.textContent?.trim() || "").length > 0
	}

	private writeTextStyle(
		element: HTMLElement,
		patch: {
			bold?: boolean | "toggle"
			italic?: boolean | "toggle"
			underline?: boolean | "toggle"
			strike?: boolean | "toggle"
			textAlign?: "left" | "center" | "right"
			color?: string
			fontSize?: number | "increase" | "decrease"
		},
	): void {
		const styleSource = this.resolveTextStyleSource(element)
		const style = window.getComputedStyle(styleSource)
		const writeTargets = this.collectTextWriteTargets(element)

		if (patch.bold !== undefined) {
			const usedExec =
				patch.bold === "toggle" &&
				this.tryExecOnElementSelection(element, "bold")
			if (!usedExec) {
				const isBold = this.isBoldWeight(style.fontWeight)
				const next =
					patch.bold === "toggle" ? !isBold : Boolean(patch.bold)
				for (const el of writeTargets) {
					el.style.setProperty("font-weight", next ? "700" : "400", "important")
				}
			}
		}

		if (patch.italic !== undefined) {
			const usedExec =
				patch.italic === "toggle" &&
				this.tryExecOnElementSelection(element, "italic")
			if (!usedExec) {
				const isItalic =
					style.fontStyle === "italic" || style.fontStyle === "oblique"
				const next =
					patch.italic === "toggle" ? !isItalic : Boolean(patch.italic)
				for (const el of writeTargets) {
					el.style.setProperty(
						"font-style",
						next ? "italic" : "normal",
						"important",
					)
				}
			}
		}

		if (patch.underline !== undefined) {
			const usedExec =
				patch.underline === "toggle" &&
				this.tryExecOnElementSelection(element, "underline")
			if (!usedExec) {
				const has = this.hasTextDecoration(style, "underline")
				const next =
					patch.underline === "toggle" ? !has : Boolean(patch.underline)
				for (const el of writeTargets) {
					this.setTextDecoration(el, "underline", next)
				}
			}
		}

		if (patch.strike !== undefined) {
			const usedExec =
				patch.strike === "toggle" &&
				this.tryExecOnElementSelection(element, "strikeThrough")
			if (!usedExec) {
				const has = this.hasTextDecoration(style, "line-through")
				const next =
					patch.strike === "toggle" ? !has : Boolean(patch.strike)
				for (const el of writeTargets) {
					this.setTextDecoration(el, "line-through", next)
				}
			}
		}

		if (patch.textAlign) {
			element.style.setProperty("text-align", patch.textAlign, "important")
		}

		if (typeof patch.color === "string" && patch.color.trim()) {
			const color = patch.color.trim()
			for (const el of writeTargets) {
				el.style.setProperty("color", color, "important")
			}
		}

		if (patch.fontSize !== undefined) {
			const currentPx = this.parseFontSizePx(style.fontSize)
			let nextPx = currentPx
			if (patch.fontSize === "increase") {
				nextPx = this.stepFontSize(currentPx, 1)
			} else if (patch.fontSize === "decrease") {
				nextPx = this.stepFontSize(currentPx, -1)
			} else if (typeof patch.fontSize === "number" && Number.isFinite(patch.fontSize)) {
				nextPx = Math.max(8, Math.min(400, Math.round(patch.fontSize)))
			}
			const value = `${nextPx}px`
			for (const el of writeTargets) {
				el.style.setProperty("font-size", value, "important")
			}
		}
	}

	private parseFontSizePx(fontSize: string): number {
		const n = parseFloat(fontSize || "")
		return Number.isFinite(n) && n > 0 ? n : 16
	}

	/** Snap along common presets when possible; otherwise ±2px. */
	private stepFontSize(currentPx: number, direction: 1 | -1): number {
		const presets = [12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 64, 72, 96]
		const rounded = Math.round(currentPx)
		const idx = presets.findIndex((p) => p === rounded)
		if (idx >= 0) {
			const next = presets[idx + direction]
			if (next != null) return next
		}
		if (direction > 0) {
			const larger = presets.find((p) => p > rounded)
			if (larger != null) return larger
		} else {
			for (let i = presets.length - 1; i >= 0; i -= 1) {
				if (presets[i] < rounded) return presets[i]
			}
		}
		return Math.max(8, Math.min(400, rounded + direction * 2))
	}

	private collectTextWriteTargets(element: HTMLElement): HTMLElement[] {
		const targets = new Set<HTMLElement>([
			element,
			this.resolveTextStyleSource(element),
		])
		element
			.querySelectorAll<HTMLElement>(
				"span,a,strong,em,b,i,u,s,small,mark,del,ins,sub,sup,code,font,p,h1,h2,h3,h4,h5,h6",
			)
			.forEach((el) => {
				if ((el.textContent?.trim() || "").length > 0) targets.add(el)
			})
		return Array.from(targets)
	}

	private isBoldWeight(fontWeight: string): boolean {
		const w = (fontWeight || "").trim().toLowerCase()
		if (w === "bold" || w === "bolder") return true
		const n = parseInt(w, 10)
		return !Number.isNaN(n) && n >= 600
	}

	/** Deepest single-path phrasing leaf — where template typography often lives. */
	private resolveTextStyleSource(element: HTMLElement): HTMLElement {
		const phrasing = new Set([
			"span",
			"a",
			"strong",
			"em",
			"b",
			"i",
			"u",
			"s",
			"small",
			"mark",
			"del",
			"ins",
			"sub",
			"sup",
			"code",
			"font",
		])
		let node: HTMLElement = element
		for (let i = 0; i < 8; i += 1) {
			const kids = Array.from(node.children).filter((c) => {
				const t = c.tagName.toLowerCase()
				return t !== "br" && t !== "wbr"
			}) as HTMLElement[]
			if (kids.length !== 1) break
			const only = kids[0]
			if (!phrasing.has(only.tagName.toLowerCase())) break
			if (!(only.textContent?.trim() || "")) break
			node = only
		}
		return node
	}

	private hasTextDecoration(
		style: CSSStyleDeclaration,
		token: string,
	): boolean {
		const line = `${style.textDecorationLine || ""} ${style.textDecoration || ""}`
		return line.split(/\s+/).includes(token)
	}

	private setTextDecoration(
		element: HTMLElement,
		token: "underline" | "line-through",
		enabled: boolean,
	) {
		const style = window.getComputedStyle(element)
		const tokens = new Set(
			`${style.textDecorationLine || style.textDecoration || ""}`
				.split(/\s+/)
				.filter((t) => t && t !== "none"),
		)
		if (enabled) tokens.add(token)
		else tokens.delete(token)
		element.style.setProperty(
			"text-decoration-line",
			tokens.size ? Array.from(tokens).join(" ") : "none",
			"important",
		)
	}

	/** Returns true if execCommand ran on a non-collapsed range inside element. */
	private tryExecOnElementSelection(
		element: HTMLElement,
		command: string,
	): boolean {
		if (!element.isContentEditable) return false
		const selection = window.getSelection()
		if (
			!selection ||
			selection.isCollapsed ||
			!selection.toString().trim() ||
			!selection.anchorNode ||
			!element.contains(selection.anchorNode)
		) {
			return false
		}
		try {
			return document.execCommand(command)
		} catch {
			return false
		}
	}

	/**
	 * Inject editor-only text editing rules without touching author inline styles.
	 */
	private injectStyles(): void {
		if (document.getElementById(TEXT_EDITING_STYLE_ID)) return

		const style = document.createElement("style")
		style.id = TEXT_EDITING_STYLE_ID
		style.setAttribute("data-injected", "true")
		style.textContent = `
[data-text-editing="true"] {
	-webkit-user-select: text !important;
	user-select: text !important;
	outline: none !important;
}
/* 文本槽勿用 overflow:hidden 裁切字形；拖拽时 releaseAncestorOverflow
   才变 visible，会导致「拖一下才显示全」。图片槽仍保持 hidden 以配合 cover。 */
[data-slot-type="text"],
[data-slot-type="text"] * {
	overflow: visible !important;
}
`
		document.head.appendChild(style)
		this.injectedTextEditingStyle = style
	}

	private getElementStyles(element: EditableElement): Record<string, string> {
		const computed = window.getComputedStyle(element)
		const styles: Record<string, string> = {}

		const importantProps = [
			"color",
			"fontSize",
			"fontWeight",
			"fontFamily",
			"fontStyle",
			"lineHeight",
			"textAlign",
			"textDecoration",
			"textDecorationLine",
			"backgroundColor",
			"backgroundImage",
			"width",
			"height",
			"margin",
			"marginTop",
			"marginRight",
			"marginBottom",
			"marginLeft",
			"padding",
			"paddingTop",
			"paddingRight",
			"paddingBottom",
			"paddingLeft",
			"border",
			"borderWidth",
			"borderStyle",
			"borderColor",
			"borderRadius",
			"display",
			"position",
			"opacity",
			"boxShadow",
			"textShadow",
			"transform",
			"flexDirection",
			"justifyContent",
			"alignItems",
			"flexWrap",
			"flexGrow",
			"flexShrink",
			"flexBasis",
			"minWidth",
			"minHeight",
			"alignSelf",
			"gap",
			"gridTemplateColumns",
			"gridTemplateRows",
			"justifyItems",
		]

		importantProps.forEach((prop) => {
			const value = computed[prop as keyof CSSStyleDeclaration] as string

			// Normalize color values (convert rgb to hex)
			if (prop === "color" || prop === "backgroundColor" || prop === "borderColor") {
				styles[prop] = normalizeColor(value)
			}
			// Normalize textAlign (start/end to left/right)
			else if (prop === "textAlign") {
				styles[prop] = normalizeTextAlign(value)
			}
			// For border compound property, normalize embedded colors
			else if (prop === "border" && value.includes("rgb")) {
				// Replace rgb colors in border string with hex
				styles[prop] = value.replace(/rgb\([^)]+\)/g, (match) => normalizeColor(match))
			} else {
				styles[prop] = value
			}
		})

		// Typography often lives on nested <span>/<strong> — sample that leaf
		// so Edit panel active states match what the user sees.
		if (
			element instanceof HTMLElement &&
			this.isTextElement(element)
		) {
			const source = this.resolveTextStyleSource(element)
			if (source !== element) {
				const leaf = window.getComputedStyle(source)
				styles.color = normalizeColor(leaf.color)
				styles.fontSize = leaf.fontSize
				styles.fontWeight = leaf.fontWeight
				styles.fontFamily = leaf.fontFamily
				styles.fontStyle = leaf.fontStyle
				styles.lineHeight = leaf.lineHeight
				styles.textDecoration = leaf.textDecoration
				styles.textDecorationLine = leaf.textDecorationLine
				// text-align is usually on the block container
				styles.textAlign = normalizeTextAlign(
					computed.textAlign || leaf.textAlign,
				)
			}
		}

		const parent = element.parentElement
		if (parent) {
			const parentComputed = window.getComputedStyle(parent)
			styles.parentDisplay = parentComputed.display
			styles.parentFlexDirection = parentComputed.flexDirection
			styles.parentAlignItems = parentComputed.alignItems
		}

		// For positioning properties (top, left, right, bottom), prefer inline styles
		// because they reflect the actual values we set, not the computed values
		const positionProps = ["top", "left", "right", "bottom"]
		positionProps.forEach((prop) => {
			const inlineValue = element.style.getPropertyValue(prop)
			if (inlineValue) {
				// Use inline style if it exists
				styles[prop] = inlineValue
			} else {
				// Fall back to computed style
				styles[prop] = computed[prop as keyof CSSStyleDeclaration] as string
			}
		})

		// Debug: Log position values
		if (element.style.top || element.style.left) {
			console.log("[ElementSelector] getElementStyles position values:", {
				selector: element.tagName,
				inlineTop: element.style.top,
				inlineLeft: element.style.left,
				stylesTop: styles.top,
				stylesLeft: styles.left,
				computedTop: computed.top,
				computedLeft: computed.left,
			})
		}

		return styles
	}

	/**
	 * Collect intrinsic image metadata so parent-side image tools can share one ratio source.
	 */
	private getImageMetadata(element: EditableElement): {
		isImageElement: boolean
		intrinsicWidth?: number
		intrinsicHeight?: number
		intrinsicAspectRatio?: number
	} {
		if (!(element instanceof HTMLImageElement))
			return {
				isImageElement: false,
			}

		const intrinsicWidth = element.naturalWidth || undefined
		const intrinsicHeight = element.naturalHeight || undefined
		const intrinsicAspectRatio =
			intrinsicWidth && intrinsicHeight ? intrinsicWidth / intrinsicHeight : undefined

		return {
			isImageElement: true,
			intrinsicWidth,
			intrinsicHeight,
			intrinsicAspectRatio,
		}
	}

	/**
	 * Find the actual selectable element (handle special containers like ECharts)
	 * If element is inside a special container (e.g. ECharts), return the container
	 */
	private findSelectableElement(element: EditableElement): EditableElement {
		let current: Element | null = element

		// Traverse up the DOM tree to find special containers
		while (current && current !== document.body && current !== document.documentElement) {
			if (!(current instanceof HTMLElement) && !(current instanceof SVGSVGElement)) {
				current = current.parentElement
				continue
			}

			if (this.isChartContainer(current)) {
				return current as EditableElement
			}

			// Check for Chart.js canvas wrapper
			if (current instanceof HTMLElement) {
				const canvasChild: HTMLCanvasElement | null = current.querySelector("canvas")
				if (
					canvasChild &&
					current.childElementCount === 1 &&
					canvasChild.parentElement === current
				) {
					const parent = current.parentElement
					if (parent && parent !== document.body && parent !== document.documentElement) {
						if (this.isChartContainer(parent)) {
							current = current.parentElement
							continue
						}
					}
					return current
				}
			}

			current = current.parentElement
		}

		// No special container found, return original element
		return element
	}

	private isChartContainer(el: Element): boolean {
		if (!(el instanceof HTMLElement)) return false
		if (el.hasAttribute("_echarts_instance_")) return true
		if (el.classList.contains("chart") || el.classList.contains("chart-container")) {
			return true
		}
		if (el.hasAttribute("data-chart") || el.hasAttribute("data-chart-type")) return true
		if (el.hasAttribute("data-highcharts-chart")) return true
		return false
	}

	private isTransparentColor(color: string): boolean {
		const c = (color || "").trim().toLowerCase()
		if (!c || c === "transparent" || c === "none") return true

		const parseAlpha = (raw: string | undefined): number | null => {
			if (raw == null || raw === "") return null
			const a = raw.endsWith("%")
				? parseFloat(raw) / 100
				: parseFloat(raw)
			return Number.isNaN(a) ? null : a
		}

		// Legacy: rgba(0, 0, 0, 0) / rgb(0, 0, 0, 0)
		const legacy = c.match(
			/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+%?))?\s*\)$/,
		)
		if (legacy) {
			const a = parseAlpha(legacy[4])
			// Missing alpha ⇒ opaque; alpha ≈ 0 ⇒ transparent
			return a != null && a <= 0.01
		}

		// CSS Color 4: rgb(0 0 0 / 0) / rgba(0 0 0 / 0%)
		const modern = c.match(
			/^rgba?\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/,
		)
		if (modern) {
			const a = parseAlpha(modern[4])
			return a != null && a <= 0.01
		}

		// color(srgb … / a), lab(… / a), oklab(… / a), etc.
		const slashAlpha = c.match(/\/\s*([\d.]+%?)\s*\)\s*$/)
		if (slashAlpha) {
			const a = parseAlpha(slashAlpha[1])
			return a != null && a <= 0.01
		}

		return false
	}

	private hasVisibleBorder(cs: CSSStyleDeclaration): boolean {
		const sides = [
			{ w: cs.borderTopWidth, s: cs.borderTopStyle },
			{ w: cs.borderRightWidth, s: cs.borderRightStyle },
			{ w: cs.borderBottomWidth, s: cs.borderBottomStyle },
			{ w: cs.borderLeftWidth, s: cs.borderLeftStyle },
		]
		return sides.some(
			({ w, s }) => s && s !== "none" && s !== "hidden" && parseFloat(w || "0") > 0,
		)
	}

	/** img / picture / video / canvas / svg / CSS background-image url */
	private isImageElement(element: EditableElement): boolean {
		if (element instanceof SVGSVGElement) return true
		if (!(element instanceof HTMLElement)) return false
		const tag = element.tagName.toLowerCase()
		if (
			tag === "img" ||
			tag === "picture" ||
			tag === "video" ||
			tag === "canvas" ||
			tag === "svg"
		) {
			return true
		}
		const bg = window.getComputedStyle(element).backgroundImage
		if (bg && bg !== "none" && /url\s*\(/i.test(bg)) return true
		return false
	}

	private isInvisibleBoxShadow(shadow: string): boolean {
		const s = (shadow || "").trim().toLowerCase()
		if (!s || s === "none") return true
		// e.g. "rgba(0, 0, 0, 0) 0px 0px 0px 0px"
		const layers = s.split(/,(?![^(]*\))/)
		return layers.every((layer) => {
			const t = layer.trim()
			if (!t || t === "none" || t.includes("transparent")) return true

			const alphaMatch = t.match(
				/rgba?\(\s*[\d.]+\s*[,/\s]+[\d.]+\s*[,/\s]+[\d.]+(?:\s*[,/]\s*([\d.]+%?))?\s*\)/,
			)
			if (alphaMatch && alphaMatch[1] != null) {
				const a = alphaMatch[1].endsWith("%")
					? parseFloat(alphaMatch[1]) / 100
					: parseFloat(alphaMatch[1])
				if (!Number.isNaN(a) && a <= 0.01) return true
			}

			const nums = (t.match(/-?[\d.]+px/g) || []).map((n) =>
				Math.abs(parseFloat(n)),
			)
			return nums.length > 0 && nums.every((n) => n <= 0.01)
		})
	}

	/**
	 * Real painted chrome only (fill / stroke / shadow / media).
	 * Do NOT treat filter / outline / backdrop alone — layout wrappers
	 * often trip those and become falsely selectable.
	 */
	private hasDecorativeStyles(element: EditableElement): boolean {
		if (element instanceof SVGSVGElement) return true
		if (!(element instanceof HTMLElement)) return false

		const cs = window.getComputedStyle(element)

		if (!this.isTransparentColor(cs.backgroundColor)) return true

		const bgImage = (cs.backgroundImage || "").trim()
		if (bgImage && bgImage !== "none") {
			const layers = bgImage.split(/,(?![^(]*\))/)
			if (layers.some((l) => l.trim() !== "none")) return true
		}

		if (this.hasVisibleBorder(cs)) return true
		if (!this.isInvisibleBoxShadow(cs.boxShadow || "")) return true

		return false
	}

	/**
	 * Selectable if: text, image/media, chart block, or decorative surface.
	 * Layout `div` wrappers (flex/absolute shells) are never targets —
	 * pick the inner text leaf or a really painted shape instead.
	 * Do not use data-slot-type for selection.
	 */
	private isSelectableContent(element: EditableElement): boolean {
		if (isInjectedElement(element)) return false
		if (isSlideShellElement(element as HTMLElement)) return false
		if (this.isTextElement(element)) return true
		if (this.isImageElement(element)) return true
		if (this.isChartContainer(element)) return true

		if (element instanceof HTMLElement) {
			const tag = element.tagName.toLowerCase()
			const dataElement = (
				element.getAttribute("data-element") || ""
			).toLowerCase()
			// Bare layout div with no role: only if it actually paints pixels
			if (tag === "div" && !dataElement) {
				return this.hasDecorativeStyles(element)
			}
		}

		if (this.hasDecorativeStyles(element)) return true
		return false
	}

	/**
	 * Text node (or Element) under viewport coordinates.
	 * Prefer caretRangeFromPoint / caretPositionFromPoint; fall back to null.
	 */
	private nodeFromPoint(clientX: number, clientY: number): Node | null {
		const doc = document as Document & {
			caretRangeFromPoint?: (x: number, y: number) => Range | null
			caretPositionFromPoint?: (
				x: number,
				y: number,
			) => { offsetNode: Node; offset: number } | null
		}
		if (typeof doc.caretRangeFromPoint === "function") {
			try {
				const range = doc.caretRangeFromPoint(clientX, clientY)
				return range?.startContainer ?? null
			} catch {
				/* ignore */
			}
		}
		if (typeof doc.caretPositionFromPoint === "function") {
			try {
				const pos = doc.caretPositionFromPoint(clientX, clientY)
				return pos?.offsetNode ?? null
			} catch {
				/* ignore */
			}
		}
		return null
	}

	/**
	 * Map pointer to editable host. When the caret hits a Text node
	 * (bare text beside spans), start from that text's parent element.
	 */
	private resolveHostFromPointer(e: MouseEvent): EditableElement | null {
		const hit = this.nodeFromPoint(e.clientX, e.clientY)
		if (hit && hit.nodeType === Node.TEXT_NODE) {
			const parent = hit.parentElement
			if (parent) {
				const fromText = resolveEditableHost(parent)
				if (fromText) return fromText
			}
		}
		return resolveEditableHost(e.target)
	}

	/**
	 * From click/hover target → nearest selectable ancestor (after chart promotion).
	 */
	private resolveSelectableTarget(
		host: EditableElement,
	): EditableElement | null {
		let current: Element | null = this.findSelectableElement(host)

		while (
			current &&
			current !== document.body &&
			current !== document.documentElement
		) {
			if (isSlideShellElement(current as HTMLElement)) return null
			if (
				(current instanceof HTMLElement || current instanceof SVGSVGElement) &&
				this.isSelectableContent(current)
			) {
				return current
			}
			current = current.parentElement
		}
		return null
	}

	/**
	 * Text leaf or explicit text role (`data-element="text"`).
	 * Prefer real text tags (span/p/h1/…) and leaf divs with only text/br.
	 * A `div` that merely wraps phrasing kids (e.g. `<div><span>…</span></div>`)
	 * is a layout shell — not a target; pick the inner span instead.
	 * Selection does not consult data-slot-type.
	 */
	private isTextElement(element: EditableElement): boolean {
		if (!(element instanceof HTMLElement)) return false

		const tagName = element.tagName.toLowerCase()
		const dataElement = (
			element.getAttribute("data-element") || ""
		).toLowerCase()

		// Non-text roles
		if (
			dataElement === "image" ||
			dataElement === "shape" ||
			dataElement === "chart"
		) {
			return false
		}

		const hasText = (element.textContent?.trim() || "").length > 0

		// Explicit text role — allow nested phrasing markup
		if (dataElement === "text") {
			return hasText
		}

		const phrasingTags = new Set([
			"span",
			"a",
			"strong",
			"em",
			"b",
			"i",
			"u",
			"s",
			"small",
			"mark",
			"del",
			"ins",
			"sub",
			"sup",
			"br",
			"wbr",
			"code",
			"font",
		])

		const textTags = new Set([
			...phrasingTags,
			"p",
			"h1",
			"h2",
			"h3",
			"h4",
			"h5",
			"h6",
			"li",
			"td",
			"th",
			"label",
			"button",
			"blockquote",
			"pre",
			// leaf text boxes only (no element children except br)
			"div",
		])

		if (!textTags.has(tagName)) return false
		if (!hasText) return false

		const structuralKids = Array.from(element.children).filter((c) => {
			const t = c.tagName.toLowerCase()
			return t !== "br" && t !== "wbr"
		})

		// Layout shell wrapping other blocks (div/svg/…) — not a text target
		if (structuralKids.length > 0) {
			const onlyPhrasing = structuralKids.every((c) =>
				phrasingTags.has(c.tagName.toLowerCase()),
			)
			const hasDirectText = Array.from(element.childNodes).some(
				(n) =>
					n.nodeType === Node.TEXT_NODE &&
					(n.textContent?.trim() || "").length > 0,
			)
			// e.g. <p><span>…</span></p> or <span>a<em>b</em></span>
			// But <div><span>…</span></div> is a shell — prefer the span.
			// Exception: mixed bare text + span → allow selecting the div when
			// the pointer lands on the bare text (caret / event.target = div).
			if (onlyPhrasing) {
				if (tagName !== "div") return true
				return hasDirectText
			}

			if (!hasDirectText) return false
			// div with mixed block kids + direct text is still a shell
			if (tagName === "div") return false
			return true
		}

		// True leaf: only text / br inside
		return true
	}

	/**
	 * Get element's original rect (unrotated) and rotation angle.
	 * Must stay consistent with applyElementTransform origin math.
	 */
	private getElementRectWithRotation(element: EditableElement) {
		// Align layout mode with drag path before measuring — otherwise selecting
		// an inline title then dragging promotes it to inline-block and the orange
		// box no longer matches the glyphs (often looks shifted right).
		if (element instanceof HTMLElement) {
			prepareElementForEditorTransform(element)
		}
		const box = getUnrotatedViewportBox(element)
		return {
			rect: {
				top: box.top,
				left: box.left,
				width: box.width,
				height: box.height,
			},
			rotation: box.rotation,
		}
	}

	selectElement(element: EditableElement, multiSelect = false) {
		if (!element || isSlideShellElement(element as HTMLElement)) {
			// Clicking the canvas shell clears selection (do not free-transform the page root)
			if (!multiSelect) this.clearSelection()
			return
		}

		// Ignore injected / non-content nodes
		if (isInjectedElement(element) || !this.isSelectableContent(element)) {
			return
		}

		ensureEditorId(element)
		rememberEditorElement(element)

		// Check if element is already selected
		const isAlreadySelected = this.selectedElements.has(element)

		// In single select mode, check if we need to clear previous selections
		if (!multiSelect) {
			// If the same element is already selected and is in text editing mode,
			// don't clear selection to avoid interrupting text editing
			const isTextEditing =
				element instanceof HTMLElement &&
				element.getAttribute("data-text-editing") === "true"

			if (isAlreadySelected && isTextEditing) {
				// Just refresh the selection info without clearing
				this.notifySelectionChanged()
				console.log(
					"[ElementSelector] Element already selected and editing, refreshing:",
					getElementSelector(element),
				)
				return
			}

			// Clear previous selections for different element or non-editing state
			this.clearSelection()
		}

		// Add element to selection
		this.selectedElements.add(element)

		// Preserve the existing first-selection editing state while CSS provides visual feedback.
		const isText = this.isTextElement(element)
		if (element instanceof HTMLElement && isText) {
			releaseAncestorOverflow(element)
		}
		if (
			!multiSelect &&
			isText &&
			element instanceof HTMLElement &&
			!element.isContentEditable
		) {
			element.contentEditable = "true"
			element.setAttribute("data-text-editing", "true")
		}

		// Notify selection changed
		this.notifySelectionChanged()

		console.log(
			"[ElementSelector] Element selected:",
			getElementSelector(element),
			"multiSelect:",
			multiSelect,
			"total selected:",
			this.selectedElements.size,
		)
	}

	deselectElement() {
		this.clearSelection()
	}

	/**
	 * Clear all selections
	 */
	clearSelection() {
		// Remove editor-owned DOM state without changing author inline styles.
		this.selectedElements.forEach((element) => {
			if (
				element instanceof HTMLElement &&
				element.getAttribute("data-text-editing") === "true"
			) {
				element.contentEditable = "false"
				element.removeAttribute("data-text-editing")
			}
		})

		this.selectedElements.clear()

		// Notify parent window to clear selection highlight
		this.bridge.sendEvent("ELEMENTS_DESELECTED", {})
	}

	/**
	 * Notify parent window about selection change
	 */
	private notifySelectionChanged() {
		const count = this.selectedElements.size

		if (count === 0) {
			// No selection
			this.bridge.sendEvent("ELEMENTS_DESELECTED", {})
		} else if (count === 1) {
			// Single selection - send ELEMENT_SELECTED for backward compatibility
			const element = Array.from(this.selectedElements)[0]
			const editorId = rememberEditorElement(element)
			const selector = getElementSelector(element)
			const styles = this.getElementStyles(element)
			const { rect, rotation } = this.getElementRectWithRotation(element)
			const isText = this.isTextElement(element)
			const textContent = element.textContent?.trim() || ""
			const imageMetadata = this.getImageMetadata(element)

			this.bridge.sendEvent("ELEMENT_SELECTED", {
				selector,
				editorId,
				tagName: element.tagName.toLowerCase(),
				...imageMetadata,
				...readElementMeta(element),
				computedStyles: styles,
				rect,
				rotation,
				isTextElement: isText,
				textContent: isText ? textContent : undefined,
			})
		} else {
			// Multiple selection - send ELEMENTS_SELECTED
			const elements = this.getSelectedElementsInfo()

			this.bridge.sendEvent("ELEMENTS_SELECTED", {
				elements,
			})
		}
	}

	private bindEvents() {
		// Mouse move
		document.addEventListener("mousemove", (e) => {
			if (!this.enabled) return

			const host = this.resolveHostFromPointer(e)
			if (!host) {
				if (this.hoveredElement) {
					this.hoveredElement = null
					this.bridge.sendEvent("ELEMENT_HOVER_END", {})
				}
				return
			}

			const selectableElement = this.resolveSelectableTarget(host)
			if (!selectableElement) {
				if (this.hoveredElement) {
					this.hoveredElement = null
					this.bridge.sendEvent("ELEMENT_HOVER_END", {})
				}
				return
			}

			// Update hovered element
			if (this.hoveredElement !== selectableElement) {
				this.hoveredElement = selectableElement

				// Send hover event to parent window (only if not already selected)
				if (!this.isSelected(selectableElement)) {
					const rect = selectableElement.getBoundingClientRect()
					this.bridge.sendEvent("ELEMENT_HOVERED", {
						rect: {
							top: rect.top,
							left: rect.left,
							width: rect.width,
							height: rect.height,
						},
					})
				}
			}
		})

		// Mouse out
		document.addEventListener("mouseout", (e) => {
			if (!this.enabled) return

			const host = this.resolveHostFromPointer(e)
			if (host && !this.isSelected(host)) {
				// Clear hover effect in parent window
				this.bridge.sendEvent("ELEMENT_HOVER_END", {})
			}
		})

		// Click
		document.addEventListener(
			"click",
			(e) => {
				if (!this.enabled) return

				const host = this.resolveHostFromPointer(e)
				if (!host) return

				// Check if there's a text selection - if so, don't trigger element selection
				// This prevents accidentally selecting other elements when releasing mouse after text selection
				const selection = window.getSelection()
				const hasTextSelection =
					selection && !selection.isCollapsed && selection.toString().trim().length > 0

				if (hasTextSelection) {
					// User is selecting text, don't trigger element selection
					console.log(
						"[ElementSelector] Text selection detected, skipping element selection",
					)
					return
				}

				e.preventDefault()
				e.stopPropagation()

				const selectableElement = this.resolveSelectableTarget(host)

				// No selectable content / shell: clear selection
				if (!selectableElement) {
					this.deselectElement()
					return
				}

				if (e.shiftKey) {
					// Shift + Click: Multi-select mode
					if (this.isSelected(selectableElement)) {
						// Already selected - remove from selection
						this.removeFromSelection(selectableElement)
						console.log(
							"[ElementSelector] Removed from selection:",
							getElementSelector(selectableElement),
						)
					} else {
						// Not selected - add to selection
						this.selectElement(selectableElement, true)
						console.log(
							"[ElementSelector] Added to selection:",
							getElementSelector(selectableElement),
						)
					}
				} else {
					// Normal click: Single-select mode
					const wasAlreadySelected =
						this.selectedElements.size === 1 && this.isSelected(selectableElement)

					if (wasAlreadySelected) {
						// Second click on already selected text element - enable text editing
						const isText = this.isTextElement(selectableElement)
						if (isText && this.onTextEditingRequest) {
							const selector = getElementSelector(selectableElement)
							// Call text editing callback
							this.onTextEditingRequest(selector)
							console.log(
								"[ElementSelector] Second click on selected text element, requesting text editing:",
								selector,
							)
						}
					} else {
						// First click or different element - select element (clear others)
						this.selectElement(selectableElement, false)
					}
				}
			},
			true,
		)

		// Keyboard shortcuts
		document.addEventListener("keydown", (e) => {
			if (!this.enabled || this.selectedElements.size === 0) return

			// Escape - deselect all
			if (e.key === "Escape") {
				e.preventDefault()
				this.deselectElement()
			}
		})
	}

	enable() {
		console.log("[ElementSelector] Enabling selection mode")
		this.enabled = true
		releaseAllTextSlotOverflow()
	}

	disable() {
		console.log("[ElementSelector] Disabling selection mode")
		this.enabled = false
		this.deselectElement()

		// Clean up editor-owned DOM state without changing author inline styles.
		const editingElements = document.querySelectorAll("[data-text-editing='true']")
		editingElements.forEach((element) => {
			if (element instanceof HTMLElement) {
				element.contentEditable = "false"
				element.removeAttribute("data-text-editing")
				element.removeAttribute("data-previous-content")
			}
		})

		// Notify parent to clear all highlights
		this.bridge.sendEvent("ELEMENT_HOVER_END", {})
	}

	/**
	 * Update selected elements position (for scroll/resize events)
	 */
	private updateSelectedElementPosition() {
		if (this.selectedElements.size === 0 || !this.enabled) return

		// Re-notify selection changed to update positions
		this.notifySelectionChanged()
	}

	/**
	 * Bind scroll listener to update element position on scroll
	 */
	private bindScrollListener() {
		const handleScroll = () => {
			if (!this.enabled || this.selectedElements.size === 0) return

			// Debounce updates using requestAnimationFrame
			if (this.updateTimer) {
				window.cancelAnimationFrame(this.updateTimer)
			}

			this.updateTimer = window.requestAnimationFrame(() => {
				this.updateSelectedElementPosition()
			})
		}

		// Listen to all scroll events (including nested scroll containers)
		window.addEventListener("scroll", handleScroll, true)
		window.addEventListener("resize", handleScroll)

		// Store cleanup for later
		this.scrollCleanup = () => {
			window.removeEventListener("scroll", handleScroll, true)
			window.removeEventListener("resize", handleScroll)
			if (this.updateTimer) {
				window.cancelAnimationFrame(this.updateTimer)
			}
		}
	}

	destroy() {
		this.disable()
		this.selectedElements.clear()
		this.hoveredElement = null

		// Cleanup scroll listeners
		if (this.scrollCleanup) {
			this.scrollCleanup()
			this.scrollCleanup = null
		}

		// Remove only the style node owned by this selector instance.
		this.injectedTextEditingStyle?.remove()
		this.injectedTextEditingStyle = null
	}
}
