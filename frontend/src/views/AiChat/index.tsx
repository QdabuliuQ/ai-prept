import { SafeMarkdown } from "@/components/SafeMarkdown";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { usePageActiveStore, usePPTStore, useSlideSelectionStore } from "@/store";
import {
  elementChipLabel,
  toAssistElementTarget,
} from "@/utils/aiChatElement";
import { buildAssistSummaryMarkdown } from "@/utils/aiChatSummary";
import {
  applyEditorDocToStore,
  fetchEditorTemplate,
  pollEditorJob,
  startEditorAssist,
  type AssistElementTarget,
  type EditorAiMode,
} from "@/utils/editorAiChat";
import {
  fetchGalleryModels,
  pickModel,
  pickProvider,
  readModelPrefs,
  writeModelPrefs,
  type GalleryProviderOption,
} from "@/utils/galleryModels";
import { streamText } from "@/utils/streamText";
import { ArrowUp, ImageIcon, Type, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { EmptyDeckArt, PanelCornerPattern, TitleMark } from "./Decor";
import styles from "./index.module.less";

type ChatRole = "user" | "assistant" | "error" | "busy";

type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
  /** When true, `text` is markdown and rendered via SafeMarkdown. */
  markdown?: boolean;
  streaming?: boolean;
  elementLabel?: string;
};

type ModelSelectKey =
  | "llmProvider"
  | "llmModel"
  | "imageProvider"
  | "imageModel";

let msgSeq = 0;
function nextMsgId() {
  msgSeq += 1;
  return `m_${Date.now()}_${msgSeq}`;
}

function loadingKey(intent: EditorAiMode | "assist") {
  if (intent === "generate") return "aiChatPanel.generating" as const;
  if (intent === "delete") return "aiChatPanel.deleting" as const;
  if (intent === "assist") return "aiChatPanel.assisting" as const;
  return "aiChatPanel.rewriting" as const;
}

const STARTER_KEYS = [
  "aiChatPanel.starterRewrite",
  "aiChatPanel.starterGenerate",
  "aiChatPanel.starterDelete",
] as const;

export const AiChatPanel: FC = () => {
  const { t } = useTranslation();
  const templateId = usePPTStore((s) => s.templateId);
  const pages = usePPTStore((s) => s.pages);
  const pageActive = usePageActiveStore((s) => s.pageActive);
  const slideSelected = useSlideSelectionStore((s) => s.selected);

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  /** Pinned element target for the next assist turn (survives canvas deselect). */
  const [pinnedElement, setPinnedElement] = useState<AssistElementTarget | null>(
    null,
  );
  const [pinnedLabel, setPinnedLabel] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [llmProviders, setLlmProviders] = useState<GalleryProviderOption[]>([]);
  const [imageProviders, setImageProviders] = useState<GalleryProviderOption[]>(
    [],
  );
  const [llmProvider, setLlmProvider] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [imageProvider, setImageProvider] = useState("");
  const [imageModel, setImageModel] = useState("");
  const [modelsReady, setModelsReady] = useState(false);
  const [openModelSelect, setOpenModelSelect] = useState<ModelSelectKey | null>(
    null,
  );

  const pageIndex = useMemo(
    () => pages.findIndex((p) => p.id === pageActive),
    [pages, pageActive],
  );
  const activePage = pageIndex >= 0 ? pages[pageIndex] : undefined;
  const sourceFile = activePage?.sourceFile;

  const canSend = Boolean(templateId && input.trim().length >= 4 && !busy);

  const llmModelOptions = useMemo(() => {
    const p = llmProviders.find((x) => x.id === llmProvider);
    return p?.models || [];
  }, [llmProviders, llmProvider]);

  const imageModelOptions = useMemo(() => {
    const p = imageProviders.find((x) => x.id === imageProvider);
    return p?.models || [];
  }, [imageProviders, imageProvider]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const catalog = await fetchGalleryModels();
      if (cancelled || !catalog) return;
      const { llmProviders: llms, imageProviders: images, defaults } = catalog;
      setLlmProviders(llms);
      setImageProviders(images);
      const saved = readModelPrefs();
      const lp = pickProvider(
        llms,
        saved.llmProvider || defaults.llmProvider,
        "groq",
      );
      const ip = pickProvider(
        images,
        saved.imageProvider || defaults.imageProvider,
        "siliconflow",
      );
      setLlmProvider(lp?.id || "");
      setLlmModel(pickModel(lp, saved.llmModel || defaults.llmModel));
      setImageProvider(ip?.id || "");
      setImageModel(pickModel(ip, saved.imageModel || defaults.imageModel));
      setModelsReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!modelsReady || !llmProvider || !imageProvider) return;
    writeModelPrefs({
      llmProvider,
      llmModel,
      imageProvider,
      imageModel,
    });
  }, [
    modelsReady,
    llmProvider,
    llmModel,
    imageProvider,
    imageModel,
  ]);

  const onModelSelectOpenChange = (key: ModelSelectKey, open: boolean) => {
    if (open) {
      setOpenModelSelect(key);
      return;
    }
    setOpenModelSelect((cur) => (cur === key ? null : cur));
  };

  const onLlmProviderChange = (id: string) => {
    setLlmProvider(id);
    const p = llmProviders.find((x) => x.id === id);
    setLlmModel(pickModel(p));
  };

  const onImageProviderChange = (id: string) => {
    setImageProvider(id);
    const p = imageProviders.find((x) => x.id === id);
    setImageModel(pickModel(p));
  };

  const push = (role: ChatRole, text: string, extra?: Partial<ChatMessage>) => {
    setMessages((prev) => [
      ...prev,
      { id: nextMsgId(), role, text, ...extra },
    ]);
  };

  // Selecting a canvas element attaches it as the chat edit target.
  useEffect(() => {
    if (!slideSelected) return;
    setPinnedElement(toAssistElementTarget(slideSelected));
    setPinnedLabel(elementChipLabel(slideSelected));
  }, [slideSelected]);

  // Clear pin when leaving the page / pack.
  useEffect(() => {
    setPinnedElement(null);
    setPinnedLabel(null);
  }, [pageActive, templateId]);

  const clearPinnedElement = () => {
    setPinnedElement(null);
    setPinnedLabel(null);
  };

  const updateLastMatching = (
    match: (m: ChatMessage) => boolean,
    patch: Partial<ChatMessage>,
  ) => {
    setMessages((prev) => {
      const copy = [...prev];
      for (let i = copy.length - 1; i >= 0; i--) {
        if (match(copy[i])) {
          copy[i] = { ...copy[i], ...patch };
          break;
        }
      }
      return copy;
    });
  };

  const replaceLastBusy = (
    text: string,
    role: ChatRole = "assistant",
    extra?: Partial<ChatMessage>,
  ) => {
    updateLastMatching(
      (m) => m.role === "busy" || m.role === "assistant",
      {
        role,
        text,
        markdown: false,
        streaming: false,
        ...extra,
      },
    );
  };

  const handleSend = async () => {
    const issue = input.trim();
    if (!templateId || busy || issue.length < 4) return;

    setInput("");
    push("user", issue, pinnedLabel ? { elementLabel: pinnedLabel } : undefined);
    setBusy(true);
    push("busy", t("aiChatPanel.understanding"));

    const ac = new AbortController();
    abortRef.current = ac;
    const elementPayload = pinnedElement;

    try {
      const { jobId, intent } = await startEditorAssist({
        templateId,
        issue,
        file: sourceFile,
        pageIndex: pageIndex >= 0 ? pageIndex : undefined,
        llmProvider: llmProvider || undefined,
        llmModel: llmModel || undefined,
        imageProvider: imageProvider || undefined,
        imageModel: imageModel || undefined,
        element: elementPayload,
      });

      const loadingText = t(loadingKey(intent));
      replaceLastBusy(loadingText, "busy");

      const job = await pollEditorJob(jobId, {
        signal: ac.signal,
        // WorkBuddy / 生图改页常超过 3 分钟；前端原先 90×2s≈3min 会误报超时
        intervalMs: intent === "delete" ? 600 : 2500,
        maxAttempts: intent === "delete" ? 40 : 240,
      });
      const doc = await fetchEditorTemplate(templateId);
      const resolvedIntent = String(job.intent || intent || "rewrite").toLowerCase();
      const activate =
        resolvedIntent === "generate"
          ? job.resultFile || job.activateFile || null
          : resolvedIntent === "delete"
            ? job.activateFile || null
            : sourceFile || job.resultFile || job.slideFile || null;
      const cacheToken =
        Array.isArray(job.regeneratedImages) && job.regeneratedImages.length
          ? Date.now()
          : null;
      applyEditorDocToStore(doc, {
        activateSourceFile: activate,
        assetCacheToken: cacheToken,
      });

      const summaryMd =
        (job.summaryMarkdown && String(job.summaryMarkdown).trim()) ||
        buildAssistSummaryMarkdown({
          t: (key, opts) => String(t(key as never, opts as never)),
          intent:
            resolvedIntent === "generate" || resolvedIntent === "delete"
              ? resolvedIntent
              : "rewrite",
          issue,
          pageIndex: pageIndex >= 0 ? pageIndex : undefined,
          sourceFile,
          job,
        });

      replaceLastBusy("", "assistant", { markdown: true, streaming: true });
      await streamText(
        summaryMd,
        (visible) => {
          updateLastMatching(
            (m) => m.role === "assistant" && Boolean(m.streaming || m.markdown),
            {
              text: visible,
              markdown: true,
              streaming: true,
            },
          );
        },
        { signal: ac.signal, cps: 90 },
      );
      updateLastMatching(
        (m) => m.role === "assistant" && Boolean(m.markdown),
        { text: summaryMd, markdown: true, streaming: false },
      );
    } catch (e) {
      if (ac.signal.aborted || String(e) === "Error: ABORTED") {
        return;
      }
      const msg = e instanceof Error ? e.message : String(e);
      replaceLastBusy(msg, "error");
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  };

  const modelSelectsDisabled = busy || !modelsReady;

  return (
    <aside className={styles.panel} aria-label={t("aiChatPanel.title")}>
      <PanelCornerPattern />
      <header className={styles.header}>
        <div className={styles.brandRow}>
          <div className={styles.titleGroup}>
            <TitleMark />
            <h2 className={styles.title}>{t("aiChatPanel.title")}</h2>
          </div>
        </div>
      </header>

      <div ref={listRef} className={styles.messages} role="log" aria-live="polite">
        {messages.length === 0 ? (
          <div className={styles.empty}>
            <EmptyDeckArt />
            <p className={styles.emptyTitle}>{t("aiChatPanel.emptyTitle")}</p>
            <p className={styles.emptyBody}>{t("aiChatPanel.emptyHint")}</p>
            <p className={styles.emptyHintExtra}>{t("aiChatPanel.emptyElementHint")}</p>
            <div className={styles.starters} role="group" aria-label={t("aiChatPanel.starters")}>
              {STARTER_KEYS.map((key) => {
                const label = t(key);
                return (
                  <button
                    key={key}
                    type="button"
                    className={styles.starter}
                    disabled={busy || !templateId}
                    onClick={() => {
                      setInput(label);
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={`${styles.turn} ${
                m.role === "user"
                  ? styles.turnUser
                  : m.role === "error"
                    ? styles.turnError
                    : styles.turnAssistant
              }`}
            >
              <div
                className={`${styles.bubble} ${
                  m.role === "user"
                    ? styles.bubbleUser
                    : m.role === "error"
                      ? styles.bubbleError
                      : styles.bubbleAssistant
                } ${m.role === "busy" ? styles.bubbleBusy : ""}`}
              >
                {m.role === "busy" ? (
                  <span className={styles.pulse} aria-hidden />
                ) : null}
                {m.elementLabel ? (
                  <div className={styles.msgElementChip} title={m.elementLabel}>
                    {m.elementLabel}
                  </div>
                ) : null}
                {m.markdown ? (
                  <div className={styles.mdWrap}>
                    <SafeMarkdown className={styles.markdown}>{m.text}</SafeMarkdown>
                    {m.streaming ? (
                      <span className={styles.caret} aria-hidden />
                    ) : null}
                  </div>
                ) : (
                  <span className={styles.bubbleText}>{m.text}</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className={styles.footer}>
        <div className={styles.composer}>
          {pinnedElement && pinnedLabel ? (
            <div className={styles.elementPin} role="status">
              <span className={styles.elementPinIcon} aria-hidden>
                {pinnedElement.isImageElement || pinnedElement.imageSrc ? (
                  <ImageIcon strokeWidth={1.75} />
                ) : (
                  <Type strokeWidth={1.75} />
                )}
              </span>
              <div className={styles.elementPinBody}>
                <span className={styles.elementPinTitle}>
                  {t("aiChatPanel.elementPinned")}
                </span>
                <span className={styles.elementPinText} title={pinnedLabel}>
                  {pinnedLabel}
                </span>
              </div>
              <button
                type="button"
                className={styles.elementPinClear}
                aria-label={t("aiChatPanel.elementClear")}
                disabled={busy}
                onClick={clearPinnedElement}
              >
                <X strokeWidth={2} aria-hidden />
              </button>
            </div>
          ) : null}
          <Textarea
            value={input}
            disabled={busy || !templateId}
            placeholder={
              pinnedElement
                ? t("aiChatPanel.placeholderElement")
                : t("aiChatPanel.placeholderAgent")
            }
            className={styles.textarea}
            rows={3}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
          />
          <div className={styles.composerBar}>
            <span className={styles.composerHint}>
              {!templateId
                ? t("aiChatPanel.needTemplate")
                : !sourceFile
                  ? t("aiChatPanel.needSourceFile")
                  : t("aiChatPanel.hintEnter")}
            </span>
            <Button
              type="button"
              size="sm"
              disabled={!canSend}
              className={styles.sendBtn}
              aria-label={t("aiChatPanel.send")}
              onClick={() => void handleSend()}
            >
              {busy ? (
                t("aiChatPanel.sending")
              ) : (
                <>
                  <ArrowUp className={styles.sendIcon} aria-hidden strokeWidth={2.25} />
                  <span>{t("aiChatPanel.send")}</span>
                </>
              )}
            </Button>
          </div>
        </div>

        {(llmProviders.length > 0 || imageProviders.length > 0) && (
          <div className={styles.modelDock} aria-label={t("aiChatPanel.models")}>
            <div className={styles.modelRow}>
              <span className={styles.modelLabel}>{t("aiChatPanel.llmModels")}</span>
              <Select
                value={llmProvider || undefined}
                onValueChange={onLlmProviderChange}
                open={openModelSelect === "llmProvider"}
                onOpenChange={(open) => onModelSelectOpenChange("llmProvider", open)}
                disabled={modelSelectsDisabled || llmProviders.length === 0}
              >
                <SelectTrigger
                  aria-label={t("aiChatPanel.llmProvider")}
                  className={styles.modelTrigger}
                >
                  <SelectValue placeholder={t("aiChatPanel.provider")} />
                </SelectTrigger>
                <SelectContent className={styles.modelContent}>
                  {llmProviders.map((p) => (
                    <SelectItem
                      key={p.id}
                      value={p.id}
                      disabled={!p.configured}
                      className={styles.modelItem}
                    >
                      {p.configured
                        ? p.label
                        : t("aiChatPanel.unconfigured", { label: p.label })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={llmModel || undefined}
                onValueChange={setLlmModel}
                open={openModelSelect === "llmModel"}
                onOpenChange={(open) => onModelSelectOpenChange("llmModel", open)}
                disabled={modelSelectsDisabled || llmModelOptions.length === 0}
              >
                <SelectTrigger
                  aria-label={t("aiChatPanel.llmModel")}
                  className={`${styles.modelTrigger} ${styles.modelTriggerWide}`}
                >
                  <SelectValue placeholder={t("aiChatPanel.model")} />
                </SelectTrigger>
                <SelectContent className={styles.modelContent}>
                  {llmModelOptions.map((m) => (
                    <SelectItem key={m.id} value={m.id} className={styles.modelItem}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className={styles.modelRow}>
              <span className={styles.modelLabel}>{t("aiChatPanel.imageModels")}</span>
              <Select
                value={imageProvider || undefined}
                onValueChange={onImageProviderChange}
                open={openModelSelect === "imageProvider"}
                onOpenChange={(open) =>
                  onModelSelectOpenChange("imageProvider", open)
                }
                disabled={modelSelectsDisabled || imageProviders.length === 0}
              >
                <SelectTrigger
                  aria-label={t("aiChatPanel.imageProvider")}
                  className={styles.modelTrigger}
                >
                  <SelectValue placeholder={t("aiChatPanel.provider")} />
                </SelectTrigger>
                <SelectContent className={styles.modelContent}>
                  {imageProviders.map((p) => (
                    <SelectItem
                      key={p.id}
                      value={p.id}
                      disabled={!p.configured}
                      className={styles.modelItem}
                    >
                      {p.configured
                        ? p.label
                        : t("aiChatPanel.unconfigured", { label: p.label })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={imageModel || undefined}
                onValueChange={setImageModel}
                open={openModelSelect === "imageModel"}
                onOpenChange={(open) => onModelSelectOpenChange("imageModel", open)}
                disabled={modelSelectsDisabled || imageModelOptions.length === 0}
              >
                <SelectTrigger
                  aria-label={t("aiChatPanel.imageModel")}
                  className={`${styles.modelTrigger} ${styles.modelTriggerWide}`}
                >
                  <SelectValue placeholder={t("aiChatPanel.model")} />
                </SelectTrigger>
                <SelectContent className={styles.modelContent}>
                  {imageModelOptions.map((m) => (
                    <SelectItem key={m.id} value={m.id} className={styles.modelItem}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
};

export default AiChatPanel;
