import { usePPTStore } from "@/store";
import { useFilePreviewStore } from "@/store/zustand/filePreviewStore";
import { candidateImageUrls } from "@/utils/templateTree";
import { Close } from "@icon-park/react";
import { useEffect, useState, type FC } from "react";

function lookLikeImage(blob: Blob): boolean {
  const type = (blob.type || "").toLowerCase();
  if (!type) return blob.size > 0;
  if (type.startsWith("image/")) return true;
  if (type === "application/octet-stream") return blob.size > 0;
  return false;
}

function adminHeaders(): HeadersInit {
  try {
    const token = localStorage.getItem("webppt_admin_token");
    if (token) return { "x-admin-token": token };
  } catch {
    /* ignore */
  }
  return {};
}

/** 占据编辑画布区域的图片预览，替换幻灯片 iframe。 */
export const AssetPreview: FC = () => {
  const preview = useFilePreviewStore((s) => s.preview);
  const close = useFilePreviewStore((s) => s.close);
  const templateId = usePPTStore((s) => s.templateId);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!preview) return;

    let cancelled = false;
    let objectUrl = "";
    setFailed(false);
    setSrc(null);

    const pages = usePPTStore.getState().pages;
    const tid = templateId || "";
    const candidates = tid
      ? candidateImageUrls(tid, preview.path, pages)
      : [preview.url];

    void (async () => {
      for (const url of candidates) {
        if (cancelled) return;
        try {
          const res = await fetch(url, {
            credentials: "same-origin",
            headers: adminHeaders(),
          });
          if (!res.ok) continue;
          const blob = await res.blob();
          if (!lookLikeImage(blob)) continue;
          const next = URL.createObjectURL(blob);
          if (cancelled) {
            URL.revokeObjectURL(next);
            return;
          }
          objectUrl = next;
          setSrc(next);
          return;
        } catch {
          continue;
        }
      }
      if (!cancelled) setFailed(true);
    })();

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [preview, templateId]);

  if (!preview) return null;

  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden">
      {/* 柔和展台：暖灰底 + 径向收边，突出图片本身 */}
      <div
        className="absolute inset-0"
        style={{
          background: `
            radial-gradient(ellipse 70% 60% at 50% 45%, transparent 35%, rgba(40, 32, 24, 0.07) 100%),
            radial-gradient(circle at 50% 40%, rgba(255, 252, 248, 0.9) 0%, transparent 55%),
            linear-gradient(165deg, #f3f0eb 0%, #ebe7e1 48%, #e4dfd8 100%)
          `,
        }}
      />
      {/* 暗色模式：深色哑光展台 */}
      <div
        className="pointer-events-none absolute inset-0 hidden dark:block"
        style={{
          background: `
            radial-gradient(ellipse 70% 60% at 50% 45%, transparent 30%, rgba(0, 0, 0, 0.45) 100%),
            linear-gradient(165deg, #1c1b19 0%, #161514 50%, #121110 100%)
          `,
        }}
        aria-hidden
      />

      <div className="absolute inset-0 flex items-center justify-center p-8 sm:p-10">
        {src ? (
          <img
            src={src}
            alt=""
            draggable={false}
            className="pointer-events-none max-h-full max-w-full object-contain"
            style={{
              borderRadius: 2,
              boxShadow:
                "0 1px 2px rgba(40, 32, 24, 0.06), 0 18px 48px rgba(40, 32, 24, 0.14), 0 0 0 1px rgba(40, 32, 24, 0.06)",
            }}
          />
        ) : failed ? (
          <div className="px-6 text-center text-[13px] text-[var(--text-muted)]">
            图片无法显示
          </div>
        ) : (
          <div
            className="h-10 w-10 animate-pulse rounded-full"
            style={{
              background:
                "radial-gradient(circle, rgba(242,95,0,0.22) 0%, transparent 70%)",
            }}
            aria-hidden
          />
        )}
      </div>

      <button
        type="button"
        className="absolute top-3 right-3 z-10 inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--panel-border)] bg-[var(--panel-bg)] text-[var(--icon-color)] shadow-[var(--panel-shadow)] backdrop-blur-md transition-colors hover:bg-[var(--hover-bg)] hover:text-[var(--primary-color)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(242,95,0,0.28)]"
        onClick={close}
        aria-label="关闭图片预览"
      >
        <Close theme="outline" size="14" fill="currentColor" />
      </button>
    </div>
  );
};
