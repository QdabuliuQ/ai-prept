/**
 * Admin template generation jobs — spawn webppt-agent CLI.
 */

import { execFile, spawn, type ChildProcess } from "child_process";
import { access, mkdir, readFile, unlink, writeFile } from "fs/promises";
import path from "path";
import { promisify } from "util";
import { TEMPLATES_ROOT } from "@/server/htmlTemplates";
import { getTemplateStore } from "@/server/templates/store";
import {
  imageEnvForSelection,
  resolveImageSelection,
} from "@/server/templates/imageProviders";
import {
  llmEnvForDual,
  listLlmProvidersPublic,
  resolveLlmSelection,
  type LlmSelection,
} from "@/server/templates/llmProviders";

const execFileAsync = promisify(execFile);

export type GenerateJobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export type GenerateJobProgress = {
  total: number;
  done: number;
  ok: number;
  fail: number;
  skip: number;
  /** 最近完成的模板 id */
  lastId?: string;
  percent: number;
};

export type PackageFormat = "html-slide" | "ppt-master";

/** 生成线路：html-slide=现有 agent；ppt-master=SVG→原生PPTX→转 html-slide */
export type GeneratePipeline = "html-slide" | "ppt-master";

/** 生成仅 PPT Master；历史任务可能仍带 html-slide */
export function normalizeGeneratePipeline(
  _value?: string | null
): GeneratePipeline {
  return "ppt-master";
}

export function normalizePackageFormat(value?: string | null): PackageFormat {
  const v = (value || "").trim().toLowerCase();
  if (v === "ppt-master" || v === "pptmaster" || v === "ppt_master") {
    return "ppt-master";
  }
  return "html-slide";
}

export type GenerateJob = {
  id: string;
  prompt: string;
  mock: boolean;
  skipImage: boolean;
  /**
   * Plan 后 palette 对比度精修（colorspacious/WCAG）。
   * true→`--palette-refine`；false→`--no-palette-refine`；默认关。
   */
  paletteRefine?: boolean;
  packageFormat?: PackageFormat;
  /** 生成线路 */
  pipeline?: GeneratePipeline;
  /** ppt-master 视觉风格偏好 */
  visualStyle?: string;
  /** 历史字段；新任务固定 svg（HTML 直出已移除） */
  pptMasterRender?: "svg" | "html";
  templateId?: string;
  /** 批量数量（随机风格） */
  count?: number;
  /** 批量成功写入的模板 id 列表 */
  templateIds?: string[];
  /** 模板并行度 */
  concurrency?: number;
  /** 每包母版页数 */
  pages?: number;
  /**
   * Plan 精修：轻量骨架后用重模型重写 cover/section/closing。
   * true→AGENT_PLAN_REFINE=1；false→0；undefined→agent 默认（有轻量池才开）
   */
  planRefine?: boolean;
  /**
   * SVG 门禁失败后是否执行 bounds/LLM 修复。
   * true→`--svg-repair`（默认）；false→`--no-svg-repair`（只检不修）。
   * 仅 ppt-master render=svg 且 qualityGate≠skip 生效。
   */
  repairOnFail?: boolean;
  /**
   * 质检门禁：soft（默认 soft-pass）| strict（失败即停）| skip（跳过质检）。
   * → `--quality-gate`
   */
  qualityGate?: "soft" | "strict" | "skip";
  /**
   * 导出前剥离非法节点（animate / text@dx / 非法 clip-path）。默认 true。
   * → `--strip-unsupported` / `--no-strip-unsupported`
   */
  stripUnsupported?: boolean;
  /** LLM 提供方 / 模型（写入日志与任务展示） */
  llmProvider?: string;
  llmModel?: string;
  llmLabel?: string;
  /** 轻量模型（Plan）；缺省表示与主力相同或由 agent 自动选 */
  llmLightProvider?: string;
  llmLightModel?: string;
  llmLightLabel?: string;
  /** 文生图提供方 / 模型 */
  imageProvider?: string;
  imageModel?: string;
  imageLabel?: string;
  /** 自然语言风格意图（ensureStyle 时优先于 visualStyle） */
  styleIntent?: string;
  /** 风格不存在则自动建卡 */
  ensureStyle?: boolean;
  randomTheme?: boolean;
  randomStyle?: boolean;
  randomStyleMode?: "catalog" | "invent";
  /** 套用模板：源模板 id（remix 保版式） */
  sourceTemplateId?: string;
  status: GenerateJobStatus;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number | null;
  outputDir?: string;
  error?: string;
  log: string;
  progress?: GenerateJobProgress;
};

const JOBS_DIR = path.resolve(process.cwd(), "agent-output", "admin-jobs");
const jobs = new Map<string, GenerateJob>();
/** Active CLI children keyed by job id (lost on HMR — cancel falls back to pkill). */
const children = new Map<string, ChildProcess>();

function newJobId(): string {
  return `job_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

async function ensureJobsDir() {
  await mkdir(JOBS_DIR, { recursive: true });
}

async function persistJob(job: GenerateJob) {
  await ensureJobsDir();
  await writeFile(
    path.join(JOBS_DIR, `${job.id}.json`),
    JSON.stringify(job, null, 2),
    "utf-8"
  );
}

export function getJob(id: string): GenerateJob | undefined {
  const job = jobs.get(id);
  return job ? hydrateJobDisplay(job) : undefined;
}

export function listJobs(limit = 40): GenerateJob[] {
  return Array.from(jobs.values())
    .map(hydrateJobDisplay)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, limit);
}

/** 从日志补全 llmLabel；结束态补全残缺 progress，供表格展示 */
function hydrateJobDisplay(job: GenerateJob): GenerateJob {
  const next: GenerateJob = { ...job };
  if (!next.llmLabel && next.log) {
    const m = next.log.match(/^\[llm\]\s+(.+?)(?:\s+@\s+\S+)?$/m);
    if (m?.[1]) {
      next.llmLabel = m[1].trim();
      if (!next.llmModel) {
        const parts = next.llmLabel.split("·");
        if (parts.length > 1) next.llmModel = parts[parts.length - 1].trim();
      }
      if (!next.llmProvider) {
        if (next.llmLabel.includes("硅基")) next.llmProvider = "siliconflow";
        else if (
          next.llmLabel.includes("商汤") ||
          next.llmLabel.toLowerCase().includes("sensenova")
        ) {
          next.llmProvider = "sensenova";
        } else if (next.llmLabel.toLowerCase().includes("cloudflare")) {
          next.llmProvider = "cloudflare";
        } else if (next.llmLabel.toLowerCase().includes("pollinations")) {
          next.llmProvider = "pollinations";
        } else if (next.llmLabel.toLowerCase().includes("deepseek")) {
          next.llmProvider = "deepseek";
        }
      }
    }
  }
  if (!next.imageLabel && next.log) {
    const m = next.log.match(/^\[image\]\s+(.+?)(?:\s+@\s+\S+)?$/m);
    if (m?.[1]) {
      next.imageLabel = m[1].trim();
      if (!next.imageModel) {
        const parts = next.imageLabel.split("·");
        if (parts.length > 1) next.imageModel = parts[parts.length - 1].trim();
      }
      if (!next.imageProvider) {
        if (next.imageLabel.toLowerCase().includes("pollinations")) {
          next.imageProvider = "pollinations";
        } else {
          next.imageProvider = "openai";
        }
      }
    }
  }

  const total = Math.max(1, next.progress?.total || next.count || 1);
  const templateHits = next.templateIds?.length || (next.templateId ? 1 : 0);
  if (!next.progress) {
    if (next.status === "succeeded") {
      next.progress = {
        total,
        done: Math.max(templateHits, 1),
        ok: Math.max(templateHits, 1),
        fail: 0,
        skip: 0,
        percent: 100,
        lastId: next.templateId,
      };
    } else if (next.status === "failed") {
      next.progress = {
        total,
        done: total,
        ok: 0,
        fail: total,
        skip: 0,
        percent: 100,
      };
    } else if (next.status === "cancelled") {
      next.progress = {
        total,
        done: templateHits,
        ok: templateHits,
        fail: 0,
        skip: 0,
        percent: total > 0 ? Math.round((templateHits / total) * 100) : 0,
        lastId: next.templateId,
      };
    }
  } else if (
    next.status === "succeeded" &&
    (next.progress.ok ?? 0) === 0 &&
    templateHits > 0
  ) {
    next.progress = {
      ...next.progress,
      ok: templateHits,
      done: Math.max(next.progress.done ?? 0, templateHits),
      percent: 100,
      lastId: next.progress.lastId || next.templateId,
    };
  }

  return next;
}

function isTerminalStatus(status: GenerateJobStatus | undefined): boolean {
  return (
    status === "succeeded" || status === "failed" || status === "cancelled"
  );
}

function killProcessTree(pid: number): void {
  if (!pid || pid <= 0) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    });
    return;
  }
  try {
    // Prefer process-group kill when child was spawned detached.
    process.kill(-pid, "SIGTERM");
  } catch {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      /* already dead */
    }
  }
  // Best-effort: descendants that are not in the same group.
  void execFileAsync("pkill", ["-TERM", "-P", String(pid)]).catch(() => {});
  setTimeout(() => {
    try {
      process.kill(-pid, "SIGKILL");
    } catch {
      try {
        process.kill(pid, "SIGKILL");
      } catch {
        /* ignore */
      }
    }
    void execFileAsync("pkill", ["-KILL", "-P", String(pid)]).catch(() => {});
  }, 1500);
}

/** HMR / restarted server: find orphaned agent whose argv still contains job id. */
async function killOrphanAgentForJob(jobId: string): Promise<boolean> {
  if (process.platform === "win32") return false;
  const safeId = jobId.replace(/[^a-zA-Z0-9_-]/g, "");
  if (!safeId || safeId !== jobId) return false;
  try {
    const { stdout } = await execFileAsync("pgrep", ["-f", safeId]);
    const pids = stdout
      .split(/\s+/)
      .map((s) => Number(s.trim()))
      .filter((n) => Number.isFinite(n) && n > 0 && n !== process.pid);
    for (const pid of pids) killProcessTree(pid);
    return pids.length > 0;
  } catch {
    return false;
  }
}

function attachChild(job: GenerateJob, child: ChildProcess): void {
  children.set(job.id, child);
  const clear = () => {
    if (children.get(job.id) === child) children.delete(job.id);
  };
  child.on("close", clear);
  child.on("error", clear);
}

/**
 * Cancel a queued/running job: stop the CLI process tree and mark cancelled.
 * Already-finished templates from a partial batch are still marked pending.
 */
export async function cancelGenerateJob(id: string): Promise<GenerateJob> {
  await loadRecentJobsFromDisk();
  const job = jobs.get(id) || (await refreshJobFromDisk(id));
  if (!job) throw new Error("NOT_FOUND");
  if (isTerminalStatus(job.status)) return job;

  job.status = "cancelled";
  job.finishedAt = new Date().toISOString();
  job.error = "cancelled by user";
  job.log += `\n[cancelled] ${job.finishedAt} 用户取消生成\n`;
  const total = Math.max(1, job.progress?.total || job.count || 1);
  const done = job.progress?.done ?? 0;
  job.progress = {
    total,
    done,
    ok: job.progress?.ok ?? 0,
    fail: job.progress?.fail ?? 0,
    skip: job.progress?.skip ?? 0,
    lastId: job.progress?.lastId,
    percent: total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0,
  };
  await persistJob(job);

  const child = children.get(id);
  if (child?.pid) {
    killProcessTree(child.pid);
    try {
      child.kill("SIGTERM");
    } catch {
      /* ignore */
    }
    children.delete(id);
  } else {
    await killOrphanAgentForJob(id);
  }

  return hydrateJobDisplay(job);
}

/**
 * 删除已结束任务的日志记录（内存 + agent-output/admin-jobs/*.json）。
 * 运行中/排队中须先取消。
 */
export async function deleteGenerateJob(id: string): Promise<void> {
  await loadRecentJobsFromDisk();
  const job = jobs.get(id) || (await refreshJobFromDisk(id));
  if (!job) throw new Error("NOT_FOUND");
  if (!isTerminalStatus(job.status)) {
    throw new Error("JOB_ACTIVE");
  }

  jobs.delete(id);
  children.delete(id);
  try {
    await unlink(path.join(JOBS_DIR, `${id}.json`));
  } catch (e) {
    const err = e as NodeJS.ErrnoException;
    if (err?.code !== "ENOENT") throw e;
  }
}

export async function deleteGenerateJobs(ids: string[]): Promise<{
  deleted: string[];
  failed: { id: string; error: string }[];
}> {
  const deleted: string[] = [];
  const failed: { id: string; error: string }[] = [];
  const unique = [...new Set(ids.map((id) => id.trim()).filter(Boolean))];
  for (const id of unique) {
    try {
      await deleteGenerateJob(id);
      deleted.push(id);
    } catch (e) {
      failed.push({
        id,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }
  return { deleted, failed };
}

/** 清空全部已结束（succeeded / failed / cancelled）任务日志 */
export async function clearTerminalGenerateJobs(): Promise<{
  deleted: string[];
  failed: { id: string; error: string }[];
}> {
  await loadRecentJobsFromDisk();
  const ids = Array.from(jobs.values())
    .filter((j) => isTerminalStatus(j.status))
    .map((j) => j.id);
  return deleteGenerateJobs(ids);
}

/** 磁盘与内存合并：终端态 / 更长日志优先，避免 HMR 后内存卡在 running */
function mergeJobFromDisk(
  disk: GenerateJob,
  mem: GenerateJob | undefined
): GenerateJob {
  if (!mem) return disk;
  if (isTerminalStatus(disk.status) && !isTerminalStatus(mem.status)) {
    return disk;
  }
  if (isTerminalStatus(mem.status) && !isTerminalStatus(disk.status)) {
    return mem;
  }
  if (isTerminalStatus(disk.status) && isTerminalStatus(mem.status)) {
    const diskFin = disk.finishedAt || "";
    const memFin = mem.finishedAt || "";
    if (diskFin > memFin) return disk;
    if (memFin > diskFin) return mem;
    return (disk.log?.length || 0) >= (mem.log?.length || 0) ? disk : mem;
  }
  // 都在跑：取日志更长的（通常磁盘由同一进程写入，或旧进程收尾）
  if ((disk.log?.length || 0) > (mem.log?.length || 0)) {
    return {
      ...mem,
      ...disk,
      // 保留内存对象上的引用无必要；整份替换即可
    };
  }
  return mem;
}

export async function loadRecentJobsFromDisk(): Promise<void> {
  try {
    await ensureJobsDir();
    const { readdir } = await import("fs/promises");
    const files = await readdir(JOBS_DIR);
    for (const f of files) {
      // 跳过 report / dims 等附属文件
      if (!f.endsWith(".json") || f.includes("-report")) continue;
      try {
        const raw = await readFile(path.join(JOBS_DIR, f), "utf-8");
        const diskJob = JSON.parse(raw) as GenerateJob;
        if (!diskJob?.id) continue;
        const merged = mergeJobFromDisk(diskJob, jobs.get(diskJob.id));
        jobs.set(diskJob.id, merged);
      } catch {
        /* skip */
      }
    }
  } catch {
    /* no dir yet */
  }
}

/** 强制从磁盘重读单个任务（轮询 running 时用） */
export async function refreshJobFromDisk(
  id: string
): Promise<GenerateJob | undefined> {
  try {
    const raw = await readFile(path.join(JOBS_DIR, `${id}.json`), "utf-8");
    const diskJob = JSON.parse(raw) as GenerateJob;
    if (!diskJob?.id) return jobs.get(id);
    const merged = mergeJobFromDisk(diskJob, jobs.get(id));
    jobs.set(id, merged);
    return merged;
  } catch {
    return jobs.get(id);
  }
}

function resolveAgentBin(): {
  cmd: string;
  cwd: string;
  env: NodeJS.ProcessEnv;
} {
  const agentDir = path.resolve(process.cwd(), "agent");
  const venvBin =
    process.platform === "win32"
      ? path.join(agentDir, ".venv", "Scripts", "webppt-agent.exe")
      : path.join(agentDir, ".venv", "bin", "webppt-agent");

  return {
    cmd: venvBin,
    cwd: agentDir,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: "1",
    },
  };
}

async function pathExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

export type StartGenerateOptions = {
  prompt?: string;
  mock?: boolean;
  skipImage?: boolean;
  /** Plan 后 palette 对比度精修；默认 false */
  paletteRefine?: boolean;
  /** ignored; always ppt-master */
  packageFormat?: string;
  /** ignored; always ppt-master */
  pipeline?: string;
  visualStyle?: string;
  /** @deprecated ignored; always svg */
  pptMasterRender?: string;
  count?: number;
  pages?: number;
  /** SVG 质量修复；默认 true。false → --no-svg-repair */
  repairOnFail?: boolean;
  /** soft | strict | skip；默认 soft */
  qualityGate?: "soft" | "strict" | "skip";
  /** 默认 true → --strip-unsupported */
  stripUnsupported?: boolean;
  llmProvider?: string;
  llmModel?: string;
  imageProvider?: string;
  imageModel?: string;
  styleIntent?: string;
  ensureStyle?: boolean;
  randomTheme?: boolean;
  randomStyle?: boolean;
  randomStyleMode?: "catalog" | "invent";
};

function applyLlmEnv(childEnv: NodeJS.ProcessEnv, heavy: LlmSelection): void {
  // Plan 固定优先 DeepSeek（有 Key 时）；SVG 仍用 Admin 选的主力。
  let light: LlmSelection | undefined;
  try {
    const providers = listLlmProvidersPublic();
    const ds = providers.find((p) => p.id === "deepseek" && p.configured);
    if (ds) {
      light = resolveLlmSelection("deepseek", "deepseek-v4-flash");
    }
  } catch {
    light = undefined;
  }
  Object.assign(childEnv, llmEnvForDual(heavy, light));
  // Thinking 已下线：固定关闭
  childEnv.LLM_THINKING = "0";
}

type BatchReportRow = {
  ok?: boolean;
  template_id?: string | null;
  error?: string | null;
};

async function markPendingMany(ids: string[]): Promise<string[]> {
  const store = getTemplateStore();
  const okIds: string[] = [];
  for (const id of ids) {
    if (!id) continue;
    try {
      await store.markPending(id);
      okIds.push(id);
    } catch {
      /* skip missing */
    }
  }
  return okIds;
}

function initialProgress(total: number): GenerateJobProgress {
  return {
    total,
    done: 0,
    ok: 0,
    fail: 0,
    skip: 0,
    percent: 0,
  };
}

const PROGRESS_RE =
  /\[progress\]\s+done=(\d+)\s+total=(\d+)\s+ok=(\d+)\s+fail=(\d+)\s+skip=(\d+)\s+id=(\S+)\s+status=(\S+)/g;

function applyProgressFromLogChunk(job: GenerateJob, chunk: string) {
  let matched = false;
  for (const m of chunk.matchAll(PROGRESS_RE)) {
    matched = true;
    const done = Number(m[1]);
    const total = Number(m[2]);
    const ok = Number(m[3]);
    const fail = Number(m[4]);
    const skip = Number(m[5]);
    const lastId = m[6] === "-" ? undefined : m[6];
    job.progress = {
      total,
      done,
      ok,
      fail,
      skip,
      lastId,
      percent: total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0,
    };
    if (lastId) {
      const ids = job.templateIds ? [...job.templateIds] : [];
      if (!ids.includes(lastId) && m[7] === "OK") {
        ids.push(lastId);
        job.templateIds = ids;
        job.templateId = ids[0];
      }
    }
  }
  return matched;
}

export async function startGenerateJob(
  options: StartGenerateOptions
): Promise<GenerateJob> {
  return startPptMasterJob(options);
}

function resolvePptMasterPages(requested?: number): number {
  const n = Math.floor(Number(requested));
  if (!Number.isFinite(n)) return 7;
  return Math.min(12, Math.max(3, n));
}

/**
 * PPT Master 线路：webppt-agent ppt-master → 原生 PPTX → html-slide 包（pending）。
 */
async function startPptMasterJob(
  options: StartGenerateOptions
): Promise<GenerateJob> {
  const count = Math.max(
    1,
    Math.min(20, Math.floor(Number(options.count) || 1))
  );
  const pages = resolvePptMasterPages(options.pages);
  const visualStyle =
    (options.visualStyle || "dark-tech").trim() || "dark-tech";
  const styleIntent = (options.styleIntent || "").trim();
  const ensureStyle = Boolean(options.ensureStyle);
  const randomTheme = Boolean(options.randomTheme);
  const randomStyle = Boolean(options.randomStyle);
  const randomStyleMode =
    options.randomStyleMode === "invent" ? "invent" : "catalog";
  const svgRepair = options.repairOnFail !== false;
  const qualityGateRaw = String(options.qualityGate || "soft")
    .trim()
    .toLowerCase();
  const qualityGate =
    qualityGateRaw === "strict" || qualityGateRaw === "skip"
      ? qualityGateRaw
      : "soft";
  const stripUnsupported = options.stripUnsupported !== false;
  const paletteRefine = Boolean(options.paletteRefine);
  const hint =
    options.prompt?.trim() ||
    `虚构 AI 产品发布会：冲击力封面、章节页、能力页、数据页、收尾；禁止说明书式排版。包名用内容主题，勿把视觉风格写进书名。`;
  const llm = resolveLlmSelection(options.llmProvider, options.llmModel);
  const image = resolveImageSelection(
    options.imageProvider,
    options.imageModel,
  );
  const { cmd, cwd, env } = resolveAgentBin();

  if (!(await pathExists(cmd))) {
    throw new Error(
      `未找到 webppt-agent：${cmd}。请先在 agent/ 下创建 venv 并 pip install -e .`
    );
  }

  const pptMasterSkill = path.resolve(
    process.cwd(),
    "ppt-master",
    "skills",
    "ppt-master",
    "SKILL.md"
  );
  if (!(await pathExists(pptMasterSkill))) {
    throw new Error(
      `未找到 PPT Master Skill：${pptMasterSkill}。请将 ZIP 解压到仓库根目录 ppt-master/。`
    );
  }

  // Validate keys early (before spawn) when not mock / not skipping images
  if (!options.mock) {
    llmEnvForDual(llm); // throws if LLM keys missing
    if (!options.skipImage) {
      imageEnvForSelection(image); // throws if image keys missing
    }
  }

  const jobId = newJobId();
  const reportPath = path.join(JOBS_DIR, `${jobId}-report.json`);
  const job: GenerateJob = {
    id: jobId,
    prompt: hint,
    mock: Boolean(options.mock),
    skipImage: Boolean(options.skipImage),
    paletteRefine,
    packageFormat: "ppt-master",
    pipeline: "ppt-master",
    visualStyle,
    styleIntent: styleIntent || undefined,
    ensureStyle,
    randomTheme: randomTheme || undefined,
    randomStyle: randomStyle || undefined,
    randomStyleMode: randomStyle ? randomStyleMode : undefined,
    pptMasterRender: "svg",
    repairOnFail: svgRepair,
    qualityGate,
    stripUnsupported,
    count,
    pages,
    llmProvider: llm.provider,
    llmModel: llm.model,
    llmLabel: llm.label,
    imageProvider: image.provider,
    imageModel: image.model,
    imageLabel: image.label,
    status: "queued",
    createdAt: new Date().toISOString(),
    outputDir: TEMPLATES_ROOT,
    log: "",
    progress: initialProgress(count),
  };

  jobs.set(job.id, job);
  await persistJob(job);

  const args = [
    "ppt-master",
    "--count",
    String(count),
    "--pages",
    String(pages),
    "--style",
    visualStyle,
    "--out-root",
    TEMPLATES_ROOT,
    "--report",
    reportPath,
    "--slide-concurrency",
    "4",
  ];
  if (ensureStyle) args.push("--ensure-style");
  if (styleIntent) args.push("--style-intent", styleIntent);
  if (job.mock) args.push("--mock");
  if (job.skipImage) args.push("--skip-image");
  else args.push("--with-images");
  args.push(paletteRefine ? "--palette-refine" : "--no-palette-refine");
  args.push("--quality-gate", qualityGate);
  args.push(svgRepair ? "--svg-repair" : "--no-svg-repair");
  args.push(
    stripUnsupported ? "--strip-unsupported" : "--no-strip-unsupported",
  );
  args.push("--", hint);

  const childEnv = { ...env };
  if (job.mock) childEnv.AGENT_MOCK = "1";
  if (job.skipImage) {
    childEnv.AGENT_SKIP_IMAGE = "1";
  } else {
    delete childEnv.AGENT_SKIP_IMAGE;
  }
  childEnv.AGENT_PALETTE_REFINE = paletteRefine ? "1" : "0";
  if (!job.mock) {
    applyLlmEnv(childEnv, llm);
    if (!job.skipImage) {
      Object.assign(childEnv, imageEnvForSelection(image));
    }
  }

  job.status = "running";
  job.startedAt = new Date().toISOString();
  job.log += `[pipeline] ppt-master\n`;
  job.log += `[render] svg\n`;
  job.log += `[style] ${styleIntent ? `intent=${styleIntent} ` : ""}${visualStyle}${ensureStyle ? " ensure" : ""}\n`;
  if (randomTheme) job.log += `[random-theme] on\n`;
  if (randomStyle) job.log += `[random-style] ${randomStyleMode}\n`;
  job.log += `[images] ${job.skipImage ? "skip" : "on"}\n`;
  if (!job.skipImage) {
    job.log += `[image] ${image.label} @ ${image.baseUrl}\n`;
  }
  job.log += `[palette-refine] ${paletteRefine ? "on" : "off"}\n`;
  job.log += `[quality-gate] ${qualityGate}\n`;
  job.log += `[svg-repair] ${svgRepair ? "on" : "off"}\n`;
  job.log += `[strip-unsupported] ${stripUnsupported ? "on" : "off"}\n`;
  job.log += `[llm] heavy=${llm.label} @ ${llm.baseUrl}\n`;
  job.log += `[pages] ${pages}\n`;
  job.log += `[count] ${count}\n`;
  job.log += `$ webppt-agent ${args.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(" ")}\n`;
  await persistJob(job);

  const child = spawn(cmd, args, {
    cwd,
    env: childEnv,
    stdio: ["ignore", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });
  attachChild(job, child);

  const append = (chunk: Buffer) => {
    if (job.status === "cancelled") return;
    const text = chunk.toString("utf-8");
    job.log += text;
    if (applyProgressFromLogChunk(job, text)) {
      /* updated */
    }
    if (job.log.length > 200_000) {
      job.log = job.log.slice(-160_000);
    }
    void persistJob(job);
  };

  child.stdout?.on("data", append);
  child.stderr?.on("data", append);

  child.on("error", (err) => {
    if (job.status === "cancelled") return;
    job.status = "failed";
    job.finishedAt = new Date().toISOString();
    job.error = err.message;
    job.log += `\n[spawn error] ${err.message}\n`;
    void persistJob(job);
  });

  child.on("close", (code) => {
    void (async () => {
      job.exitCode = code;
      if (job.status === "cancelled") {
        await persistJob(job);
        return;
      }
      job.finishedAt = new Date().toISOString();

      let succeededIds: string[] = [];
      try {
        const raw = await readFile(reportPath, "utf-8");
        const rows = JSON.parse(raw) as BatchReportRow[];
        if (Array.isArray(rows)) {
          succeededIds = rows
            .filter((r) => r.ok && r.template_id)
            .map((r) => String(r.template_id));
        }
      } catch {
        /* no report */
      }

      const marked = await markPendingMany(succeededIds);
      job.templateIds = marked;
      if (marked[0]) job.templateId = marked[0];

      if (code === 0 && marked.length > 0) {
        job.status = "succeeded";
        job.progress = {
          total: count,
          done: count,
          ok: marked.length,
          fail: Math.max(0, count - marked.length),
          skip: 0,
          percent: 100,
          lastId: marked[0],
        };
        job.log += `\n[ok] ppt-master 完成 ${marked.length}/${count}：${marked.join(", ")}\n`;
      } else if (marked.length > 0) {
        job.status = "succeeded";
        job.error = `exit ${code}（部分成功）`;
        job.progress = {
          total: count,
          done: count,
          ok: marked.length,
          fail: Math.max(0, count - marked.length),
          skip: 0,
          percent: 100,
          lastId: marked[0],
        };
        job.log += `\n[partial] exit ${code}，已入库 ${marked.length}\n`;
      } else {
        job.status = "failed";
        job.error = `exit ${code}`;
        job.progress = {
          total: count,
          done: count,
          ok: 0,
          fail: count,
          skip: 0,
          percent: 100,
        };
        job.log += `\n[fail] ppt-master exit ${code}\n`;
      }
      await persistJob(job);
    })();
  });

  return job;
}

export type StartRemixOptions = {
  sourceTemplateId: string;
  prompt: string;
  mock?: boolean;
  skipImage?: boolean;
  llmProvider?: string;
  llmModel?: string;
  imageProvider?: string;
  imageModel?: string;
};

/**
 * 套用模板：克隆源包，只改 data-slot 文案/配图，保留 theme.css 与绝对定位版式。
 */
export async function startRemixJob(
  options: StartRemixOptions,
): Promise<GenerateJob> {
  const sourceId = String(options.sourceTemplateId || "").trim();
  if (!sourceId) throw new Error("缺少源模板 id");
  const hint = options.prompt?.trim();
  if (!hint) throw new Error("请填写内容要求");

  const sourceDir = path.join(TEMPLATES_ROOT, sourceId);
  if (!(await pathExists(path.join(sourceDir, "template.json")))) {
    throw new Error(`源模板不存在：${sourceId}`);
  }

  const llm = resolveLlmSelection(options.llmProvider, options.llmModel);
  const image = resolveImageSelection(
    options.imageProvider,
    options.imageModel,
  );
  const { cmd, cwd, env } = resolveAgentBin();
  if (!(await pathExists(cmd))) {
    throw new Error(
      `未找到 webppt-agent：${cmd}。请先在 agent/ 下创建 venv 并 pip install -e .`,
    );
  }

  const skipImage = options.skipImage !== false; // remix 默认保留原图，除非显式要重生
  if (!options.mock) {
    llmEnvForDual(llm);
    if (!skipImage) {
      imageEnvForSelection(image);
    }
  }

  const jobId = newJobId();
  const reportPath = path.join(JOBS_DIR, `${jobId}-report.json`);
  const job: GenerateJob = {
    id: jobId,
    prompt: hint,
    mock: Boolean(options.mock),
    skipImage,
    packageFormat: "ppt-master",
    pipeline: "ppt-master",
    sourceTemplateId: sourceId,
    count: 1,
    pages: undefined,
    llmProvider: llm.provider,
    llmModel: llm.model,
    llmLabel: llm.label,
    imageProvider: image.provider,
    imageModel: image.model,
    imageLabel: image.label,
    status: "queued",
    createdAt: new Date().toISOString(),
    outputDir: TEMPLATES_ROOT,
    log: "",
    progress: initialProgress(1),
  };

  jobs.set(job.id, job);
  await persistJob(job);

  const args = [
    "remix-template",
    sourceId,
    "--out-root",
    TEMPLATES_ROOT,
    "--report",
    reportPath,
    "--prompt",
    hint,
  ];
  if (job.mock) args.push("--mock");
  if (skipImage) args.push("--skip-image");
  else args.push("--with-images");

  const childEnv = { ...env };
  if (job.mock) childEnv.AGENT_MOCK = "1";
  if (!job.mock) {
    applyLlmEnv(childEnv, llm);
    if (!skipImage) {
      Object.assign(childEnv, imageEnvForSelection(image));
    }
  }

  job.status = "running";
  job.startedAt = new Date().toISOString();
  job.log += `[pipeline] remix-template\n`;
  job.log += `[source] ${sourceId}\n`;
  job.log += `[mode] keep layout/theme; replace text/image slots only\n`;
  job.log += `[images] ${skipImage ? "keep" : "regenerate"}\n`;
  job.log += `[llm] ${llm.label} @ ${llm.baseUrl}\n`;
  job.log += `$ webppt-agent ${args.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(" ")}\n`;
  await persistJob(job);

  const child = spawn(cmd, args, {
    cwd,
    env: childEnv,
    stdio: ["ignore", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });
  attachChild(job, child);

  const append = (chunk: Buffer) => {
    if (job.status === "cancelled") return;
    const text = chunk.toString("utf-8");
    job.log += text;
    if (applyProgressFromLogChunk(job, text)) {
      /* updated */
    }
    if (job.log.length > 200_000) {
      job.log = job.log.slice(-160_000);
    }
    void persistJob(job);
  };

  child.stdout?.on("data", append);
  child.stderr?.on("data", append);

  child.on("error", (err) => {
    if (job.status === "cancelled") return;
    job.status = "failed";
    job.finishedAt = new Date().toISOString();
    job.error = err.message;
    job.log += `\n[spawn error] ${err.message}\n`;
    void persistJob(job);
  });

  child.on("close", (code) => {
    void (async () => {
      job.exitCode = code;
      if (job.status === "cancelled") {
        await persistJob(job);
        return;
      }
      job.finishedAt = new Date().toISOString();

      let succeededIds: string[] = [];
      try {
        const raw = await readFile(reportPath, "utf-8");
        const rows = JSON.parse(raw) as BatchReportRow[];
        if (Array.isArray(rows)) {
          succeededIds = rows
            .filter((r) => r.ok && r.template_id)
            .map((r) => String(r.template_id));
        }
      } catch {
        /* no report */
      }

      const marked = await markPendingMany(succeededIds);
      job.templateIds = marked;
      if (marked[0]) job.templateId = marked[0];

      if (code === 0 && marked.length > 0) {
        job.status = "succeeded";
        job.progress = {
          total: 1,
          done: 1,
          ok: marked.length,
          fail: 0,
          skip: 0,
          percent: 100,
          lastId: marked[0],
        };
        job.log += `\n[ok] remix 完成：${marked.join(", ")}\n`;
      } else if (marked.length > 0) {
        job.status = "succeeded";
        job.error = `exit ${code}（已产出）`;
        job.progress = {
          total: 1,
          done: 1,
          ok: marked.length,
          fail: 0,
          skip: 0,
          percent: 100,
          lastId: marked[0],
        };
        job.log += `\n[partial] exit ${code}，已入库 ${marked.length}\n`;
      } else {
        job.status = "failed";
        job.error = `exit ${code}`;
        job.progress = {
          total: 1,
          done: 1,
          ok: 0,
          fail: 1,
          skip: 0,
          percent: 100,
        };
        job.log += `\n[fail] remix-template exit ${code}\n`;
      }
      await persistJob(job);
    })();
  });

  return job;
}

export const startBatchGenerateJob = startGenerateJob;
