import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "模板后台 · WebPPT",
  description: "生成、审批与管理 HTML PPT 模板",
};

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
