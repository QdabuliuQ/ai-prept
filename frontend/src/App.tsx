import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import GalleryHome from "@/pages/GalleryHome";

const EditorPage = lazy(() => import("./spa/EditorPage"));
const AdminPage = lazy(() => import("./spa/AdminPage"));
const TemplatesPage = lazy(() => import("./spa/TemplatesRoute"));

function Fallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-sm text-muted-foreground">
      加载中…
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Fallback />}>
      <Routes>
        <Route path="/" element={<GalleryHome />} />
        <Route path="/edit" element={<EditorPage />} />
        <Route path="/editor" element={<Navigate to="/edit" replace />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/templates" element={<TemplatesPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
