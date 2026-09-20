/**
 * Element Selector
 * Handles element selection and highlighting
 */

import type { EditorBridge } from "./core/EditorBridge";
import {
  ensureEditorId,
  getElementSelector,
  isInjectedElement,
  rememberEditorElement,
  resolveEditableHost,
  type EditableElement,
} from "./utils/dom";
import { normalizeColor, normalizeTextAlign } from "./utils/css";
import { isSlideShellElement, getUnrotatedViewportBox } from "./utils/transform";

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
		if (!c || c === "transparent") return true
		const rgba = c.match(
			/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/,
		)
		if (rgba && rgba[4] != null) {
			const a = rgba[4].endsWith("%")
				? parseFloat(rgba[4]) / 100
				: parseFloat(rgba[4])
			if (!Number.isNaN(a) && a <= 0.01) return true
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

	/**
	 * Non-text visual chrome: fill, stroke, shadow, filter, etc.
	 */
	private hasDecorativeStyles(element: EditableElement): boolean {
		if (element instanceof SVGSVGElement) return true
		if (!(element instanceof HTMLElement)) return false

		const cs = window.getComputedStyle(element)

		if (cs.backgroundImage && cs.backgroundImage !== "none") return true
		if (!this.isTransparentColor(cs.backgroundColor)) return true
		if (this.hasVisibleBorder(cs)) return true
		if (cs.boxShadow && cs.boxShadow !== "none") return true
		if (cs.filter && cs.filter !== "none") return true
		if (
			cs.outlineStyle &&
			cs.outlineStyle !== "none" &&
			parseFloat(cs.outlineWidth || "0") > 0
		) {
			return true
		}
		const backdrop =
			(cs as CSSStyleDeclaration & { backdropFilter?: string }).backdropFilter ||
			(cs as CSSStyleDeclaration & { webkitBackdropFilter?: string })
				.webkitBackdropFilter
		if (backdrop && backdrop !== "none") return true

		return false
	}

	/**
	 * Selectable if: text, image/media, chart block, or decorative surface.
	 * Plain layout wrappers (flex/grid with no chrome) are skipped.
	 */
	private isSelectableContent(element: EditableElement): boolean {
		if (isInjectedElement(element)) return false
		if (isSlideShellElement(element as HTMLElement)) return false
		if (this.isTextElement(element)) return true
		if (this.isImageElement(element)) return true
		if (this.isChartContainer(element)) return true
		if (this.hasDecorativeStyles(element)) return true
		return false
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
	 * Text leaf only: the innermost tag that actually wraps text.
	 * e.g. `<div><span>text</span></div>` → span yes, outer div no.
	 * `<div>plain</div>` (no element children) → div yes.
	 */
	private isTextElement(element: EditableElement): boolean {
		if (!(element instanceof HTMLElement)) return false

		const tagName = element.tagName.toLowerCase()

		const textTags = new Set([
			"p",
			"span",
			"h1",
			"h2",
			"h3",
			"h4",
			"h5",
			"h6",
			"a",
			"li",
			"td",
			"th",
			"label",
			"button",
			"blockquote",
			"pre",
			"code",
			"strong",
			"em",
			"b",
			"i",
			"small",
			"mark",
			"del",
			"ins",
			"sub",
			"sup",
		])

		const allowTag = textTags.has(tagName) || tagName === "div"
		if (!allowTag) return false

		const structuralKids = Array.from(element.children).filter((c) => {
			const t = c.tagName.toLowerCase()
			return t !== "br" && t !== "wbr"
		})

		// Wrapper with only element children (div>span): not the text leaf
		if (structuralKids.length > 0) {
			const hasDirectText = Array.from(element.childNodes).some(
				(n) =>
					n.nodeType === Node.TEXT_NODE &&
					(n.textContent?.trim() || "").length > 0,
			)
			// Layout div that nests other nodes is never a text leaf
			if (tagName === "div") return false
			// Inline text tags may mix own text + nested emphasis: <span>a<em>b</em></span>
			if (!hasDirectText) return false
			return textTags.has(tagName)
		}

		// True leaf: only text / br inside
		return (element.textContent?.trim() || "").length > 0
	}

	/**
	 * Get element's original rect (unrotated) and rotation angle.
	 * Must stay consistent with applyElementTransform origin math.
	 */
	private getElementRectWithRotation(element: EditableElement) {
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

			const host = resolveEditableHost(e.target)
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

			const host = resolveEditableHost(e.target)
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

				const host = resolveEditableHost(e.target)
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
