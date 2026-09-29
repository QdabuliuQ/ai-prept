import { useState } from "react";
import { toast } from "sonner";
import { ThemeSwitcher } from "@/components";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { adminFetch, clearToken, writeToken } from "./api";
import { LoadingButton } from "./shared";

export function LoginGate({ onOk }: { onOk: () => void }) {
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!token.trim()) {
      toast.warning("请输入 ADMIN_TOKEN");
      return;
    }
    setLoading(true);
    try {
      writeToken(token.trim());
      await adminFetch("/api/admin/templates");
      toast.success("已登录");
      onOk();
    } catch (err) {
      clearToken();
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background p-6">
      <div className="absolute right-4 top-4">
        <ThemeSwitcher />
      </div>
      <Card className="w-full max-w-md shadow-sm">
        <CardHeader>
          <CardTitle className="text-xl">WebPPT 模板后台</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm text-muted-foreground">
            使用环境变量{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              ADMIN_TOKEN
            </code>{" "}
            登录。请在{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              .env.local
            </code>{" "}
            配置后重启{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              npm run dev
            </code>
            。
          </p>
          <form onSubmit={(e) => void submit(e)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="admin-token">Admin Token</Label>
              <Input
                id="admin-token"
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="与 ADMIN_TOKEN 一致"
                autoComplete="current-password"
              />
            </div>
            <LoadingButton type="submit" className="w-full" loading={loading}>
              进入后台
            </LoadingButton>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
