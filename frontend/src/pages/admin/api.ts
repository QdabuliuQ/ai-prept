const TOKEN_KEY = "webppt_admin_token";
const TOKEN_HEADER = "x-admin-token";

export function readToken(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function writeToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  document.cookie = `webppt_admin_token=${encodeURIComponent(token)}; path=/; SameSite=Lax`;
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  document.cookie = "webppt_admin_token=; path=/; Max-Age=0; SameSite=Lax";
}

export async function adminFetch(url: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  const token = readToken();
  if (token) headers.set(TOKEN_HEADER, token);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(url, { ...init, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.message || data.error || `HTTP ${res.status}`);
  }
  return data;
}

/** Binary download with admin auth (e.g. source.pptx). */
export async function adminFetchBinary(
  url: string,
  init: RequestInit = {},
): Promise<ArrayBuffer> {
  const headers = new Headers(init.headers || {});
  const token = readToken();
  if (token) headers.set(TOKEN_HEADER, token);
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(
      (data as { message?: string; error?: string }).message ||
        (data as { error?: string }).error ||
        `HTTP ${res.status}`,
    );
  }
  return res.arrayBuffer();
}
