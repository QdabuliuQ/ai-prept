import { EDITOR_TRANSFORM_ATTRS } from "./transform";

/**
 * Content Cleaner — strip editor-injected nodes/attrs before persisting HTML
 */

export class ContentCleaner {
  static cleanDocument(html: string): string {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    this.removeInjectedElements(doc);
    this.cleanEditingAttributes(doc);
    return this.serializeDocument(doc);
  }

  private static removeInjectedElements(doc: Document): void {
    doc.querySelectorAll("[data-injected]").forEach((el) => {
      if (
        ["SCRIPT", "STYLE", "LINK", "META"].includes(el.tagName) ||
        el.getAttribute("data-editor-placeholder") === "true"
      ) {
        el.remove();
      } else {
        el.removeAttribute("data-injected");
      }
    });
  }

  private static cleanEditingAttributes(doc: Document): void {
    const editingClasses = ["__editor-selected", "__editor-hover"];
    const editingAttributes = [
      "contenteditable",
      "data-text-editing",
      "data-previous-content",
      "data-previous-user-select",
      "data-previous-webkit-user-select",
      ...EDITOR_TRANSFORM_ATTRS,
    ];

    doc.querySelectorAll("*").forEach((el) => {
      editingClasses.forEach((cls) => el.classList.remove(cls));
      editingAttributes.forEach((attr) => el.removeAttribute(attr));
    });

    doc.documentElement?.removeAttribute("data-injected");
    doc.body?.removeAttribute("data-injected");
  }

  private static serializeDocument(doc: Document): string {
    const doctype = doc.doctype;
    let doctypeStr = "<!DOCTYPE html>";

    if (doctype) {
      doctypeStr = `<!DOCTYPE ${doctype.name}`;
      if (doctype.publicId) {
        doctypeStr += ` PUBLIC "${doctype.publicId}"`;
      }
      if (doctype.systemId) {
        doctypeStr += ` "${doctype.systemId}"`;
      }
      doctypeStr += ">\n";
    }

    return doctypeStr + doc.documentElement.outerHTML;
  }
}
