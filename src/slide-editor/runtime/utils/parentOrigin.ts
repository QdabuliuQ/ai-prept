/**
 * Resolve the trusted parent origin for postMessage communication.
 */

let cachedOrigin: string | null = null;

export function getParentOrigin(): string {
  if (cachedOrigin !== null) return cachedOrigin;

  if (location.ancestorOrigins && location.ancestorOrigins.length > 0) {
    cachedOrigin = location.ancestorOrigins[0];
    return cachedOrigin;
  }

  if (document.referrer) {
    try {
      cachedOrigin = new URL(document.referrer).origin;
      return cachedOrigin;
    } catch {
      /* fall through */
    }
  }

  cachedOrigin = "*";
  return cachedOrigin;
}
