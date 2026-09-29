import { useEffect, useState } from "react";
import { ThemeSwitcher } from "@/components";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useThemeStore } from "@/store";
import { adminFetch, clearToken, readToken } from "./api";
import { GeneratePanel } from "./GeneratePanel";
import { JobsPanel } from "./JobsPanel";
import { LoginGate } from "./LoginGate";
import { TemplatesPanel } from "./TemplatesPanel";

function AdminShell() {
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);
  const [tab, setTab] = useState("templates");
  const [focusTemplateId, setFocusTemplateId] = useState<string | null>(null);
  const themeMode = useThemeStore((state) => state.theme);
  const hydrateTheme = useThemeStore((state) => state.hydrateTheme);
  const toasterTheme = themeMode === "dark" ? "dark" : "light";

  useEffect(() => {
    hydrateTheme();
  }, [hydrateTheme]);

  useEffect(() => {
    const boot = async () => {
      if (!readToken()) {
        setReady(true);
        return;
      }
      try {
        await adminFetch("/api/admin/templates");
        setAuthed(true);
      } catch {
        clearToken();
      } finally {
        setReady(true);
      }
    };
    void boot();
  }, []);

  const logout = () => {
    clearToken();
    setAuthed(false);
  };

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        加载中…
      </div>
    );
  }

  if (!authed) {
    return (
      <>
        <Toaster theme={toasterTheme} position="top-center" />
        <LoginGate onOk={() => setAuthed(true)} />
      </>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Toaster theme={toasterTheme} position="top-center" />
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1680px] items-center justify-between px-6">
          <h1 className="text-lg font-semibold tracking-tight">
            WebPPT 模板后台
          </h1>
          <nav className="flex items-center gap-1">
            <ThemeSwitcher />
            <Button variant="ghost" size="sm" asChild>
              <a href="/">模板墙</a>
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <a href="/templates">公开模板库</a>
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <a href="/edit">编辑器</a>
            </Button>
            <Button variant="outline" size="sm" onClick={logout}>
              退出
            </Button>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1680px] px-6 py-6">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="mb-4">
            <TabsTrigger value="templates">模板管理</TabsTrigger>
            <TabsTrigger value="generate">生成模板</TabsTrigger>
            <TabsTrigger value="jobs">任务日志</TabsTrigger>
          </TabsList>
        </Tabs>
        {/* Keep panels mounted so polling / forms survive tab switches */}
        <div className={tab === "templates" ? "block" : "hidden"}>
          <TemplatesPanel
            onRemixQueued={() => setTab("jobs")}
            onRemixDone={(id) => {
              setFocusTemplateId(id);
              setTab("templates");
            }}
            focusTemplateId={focusTemplateId}
          />
        </div>
        <div className={tab === "generate" ? "block" : "hidden"}>
          <GeneratePanel
            active={tab === "generate"}
            onCreated={() => setTab("jobs")}
          />
        </div>
        <div className={tab === "jobs" ? "block" : "hidden"}>
          <JobsPanel />
        </div>
      </main>
    </div>
  );
}

export default function AdminApp() {
  return (
    <TooltipProvider delayDuration={200}>
      <AdminShell />
    </TooltipProvider>
  );
}
