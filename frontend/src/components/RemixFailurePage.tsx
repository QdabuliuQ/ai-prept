import { useNavigate } from "react-router-dom";
import logo from "@/assets/images/ai-prept-logo.png";
import { useGalleryRemixStore } from "@/store";

/**
 * Gallery remix 失败/取消：整页错误态，替换编辑器（菜单 / Header / 画布都不渲染）。
 */
export function RemixFailurePage() {
  const navigate = useNavigate();
  const error = useGalleryRemixStore((s) => s.error);
  const cancelled = useGalleryRemixStore((s) => s.errorCancelled);
  const clearFailure = useGalleryRemixStore((s) => s.clearFailure);

  if (!error) return null;

  const title = cancelled ? "生成已取消" : "生成失败";

  const goHome = () => {
    clearFailure();
    void navigate("/", { replace: true });
  };

  return (
    <div className="relative isolate flex h-[100vh] max-h-[100vh] w-[100vw] max-w-[100vw] flex-col overflow-hidden bg-[#f4f2ef]">
      <div
        className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
        aria-hidden="true"
      >
        <div className="absolute -right-[18%] -top-[30%] h-[70vw] max-h-[720px] w-[70vw] max-w-[720px] rounded-full bg-[radial-gradient(circle_at_center,rgba(242,95,0,0.16),transparent_68%)] blur-2xl" />
        <div className="absolute -bottom-[24%] -left-[12%] h-[55vw] max-h-[560px] w-[55vw] max-w-[560px] rounded-full bg-[radial-gradient(circle_at_center,rgba(0,0,0,0.05),transparent_70%)] blur-2xl" />
      </div>

      <header className="relative z-10 flex items-center px-8 py-6 sm:px-12">
        <button
          type="button"
          onClick={goHome}
          className="inline-flex items-center gap-2.5 transition-opacity hover:opacity-80"
        >
          <img src={logo} alt="" className="h-7 w-7 object-contain" />
          <span className="text-[15px] font-semibold tracking-[0.02em] text-[#1c1917]">
            Ai Prept
          </span>
        </button>
      </header>

      <main className="relative z-10 flex flex-1 flex-col items-center justify-center px-8 pb-24 sm:px-12">
        <div
          role="alert"
          className="w-full max-w-[560px] animate-[fadeInUp_0.4s_ease-out_both]"
        >
          <p className="mb-4 text-[13px] font-medium tracking-[0.12em] text-[#f25f00]">
            {cancelled ? "CANCELLED" : "ERROR"}
          </p>
          <h1 className="m-0 mb-5 text-[40px] font-semibold leading-[1.15] tracking-[-0.02em] text-[#1c1917] sm:text-[48px]">
            {title}
          </h1>
          <p className="m-0 mb-3 text-[16px] leading-[1.65] text-[#57534e]">
            {error}
          </p>
          {!cancelled ? (
            <p className="m-0 mb-10 text-[14px] leading-[1.55] text-[#a8a29e]">
              可返回模板首页重新选择模板并再次生成
            </p>
          ) : (
            <div className="mb-10" />
          )}
          <button
            type="button"
            onClick={goHome}
            className="inline-flex h-11 items-center justify-center rounded-full bg-[#f25f00] px-7 text-[14px] font-medium text-white shadow-[0_8px_24px_rgba(242,95,0,0.28)] transition-[transform,background-color] hover:bg-[#d95400] active:scale-[0.98]"
          >
            返回首页重试
          </button>
        </div>
      </main>

      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(14px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
