import type { EditorAiMode, EditorJobStatus } from "@/utils/editorAiChat";

export type SummaryI18n = {
  (key: string, opts?: Record<string, unknown>): string;
};

function escMdInline(value: string): string {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/`/g, "\\`")
    .replace(/\*/g, "\\*")
    .replace(/_/g, "\\_")
    .replace(/\[/g, "\\[")
    .replace(/\]/g, "\\]");
}

function codeSpan(value: string): string {
  const v = String(value || "").replace(/`/g, "'");
  return v ? `\`${v}\`` : "—";
}

/** Build a short markdown summary after an editor AI job succeeds. */
export function buildAssistSummaryMarkdown(options: {
  t: SummaryI18n;
  intent: EditorAiMode;
  issue: string;
  pageIndex?: number;
  sourceFile?: string;
  job: EditorJobStatus;
}): string {
  const { t, intent, issue, pageIndex, sourceFile, job } = options;
  const pageNo =
    typeof pageIndex === "number" && pageIndex >= 0 ? pageIndex + 1 : undefined;
  const file =
    job.resultFile ||
    job.activateFile ||
    job.slideFile ||
    sourceFile ||
    "";
  const title = job.resultTitle || "";
  const deleted =
    Array.isArray(job.deletedFiles) && job.deletedFiles.length
      ? job.deletedFiles
      : file
        ? [file]
        : [];

  const lines: string[] = [];
  lines.push(`### ${t("aiChatPanel.summaryTitle")}`);
  lines.push("");

  if (intent === "rewrite") {
    lines.push(`- **${t("aiChatPanel.summaryAction")}**：${t("aiChatPanel.summaryActionRewrite")}`);
    if (pageNo != null) {
      lines.push(
        `- **${t("aiChatPanel.summaryPage")}**：${t("aiChatPanel.summaryPageN", { n: pageNo })}`,
      );
    }
    if (file) {
      lines.push(`- **${t("aiChatPanel.summaryFile")}**：${codeSpan(file)}`);
    }
    lines.push(`- **${t("aiChatPanel.summaryRequest")}**：${escMdInline(issue)}`);
    lines.push(`- **${t("aiChatPanel.summaryResult")}**：${t("aiChatPanel.summaryResultRewrite")}`);
  } else if (intent === "generate") {
    lines.push(`- **${t("aiChatPanel.summaryAction")}**：${t("aiChatPanel.summaryActionGenerate")}`);
    if (pageNo != null) {
      lines.push(
        `- **${t("aiChatPanel.summaryInsertAfter")}**：${t("aiChatPanel.summaryPageN", { n: pageNo })}`,
      );
    }
    if (typeof job.insertAt === "number") {
      lines.push(
        `- **${t("aiChatPanel.summaryInsertAt")}**：${t("aiChatPanel.summaryPageN", { n: job.insertAt + 1 })}`,
      );
    }
    if (file) {
      lines.push(`- **${t("aiChatPanel.summaryFile")}**：${codeSpan(file)}`);
    }
    if (title) {
      lines.push(`- **${t("aiChatPanel.summarySlideTitle")}**：${escMdInline(title)}`);
    }
    lines.push(`- **${t("aiChatPanel.summaryRequest")}**：${escMdInline(issue)}`);
    lines.push(`- **${t("aiChatPanel.summaryResult")}**：${t("aiChatPanel.summaryResultGenerate")}`);
  } else {
    lines.push(`- **${t("aiChatPanel.summaryAction")}**：${t("aiChatPanel.summaryActionDelete")}`);
    if (pageNo != null) {
      lines.push(
        `- **${t("aiChatPanel.summaryPage")}**：${t("aiChatPanel.summaryPageN", { n: pageNo })}`,
      );
    }
    if (deleted.length) {
      lines.push(
        `- **${t("aiChatPanel.summaryDeleted")}**：${deleted.map(codeSpan).join("、")}`,
      );
    }
    lines.push(`- **${t("aiChatPanel.summaryRequest")}**：${escMdInline(issue)}`);
    lines.push(`- **${t("aiChatPanel.summaryResult")}**：${t("aiChatPanel.summaryResultDelete")}`);
  }

  return lines.join("\n");
}
