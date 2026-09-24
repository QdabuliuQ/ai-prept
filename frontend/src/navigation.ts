import { useNavigate } from "react-router-dom";

/** Next.js useRouter-compatible shim for Vite SPA. */
export function useRouter() {
  const navigate = useNavigate();
  return {
    push: (to: string) => {
      void navigate(to);
    },
    replace: (to: string) => {
      void navigate(to, { replace: true });
    },
    back: () => {
      void navigate(-1);
    },
  };
}
