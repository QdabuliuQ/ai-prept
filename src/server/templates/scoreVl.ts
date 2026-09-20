/**
 * SCORE_VL_* — OpenAI-compatible chat (DashScope Qwen-VL etc.)
 * Used for lightweight Admin helpers such as random theme prompts.
 */

import { existsSync, readFileSync } from "fs";
import path from "path";

export type ScoreVlConfig = {
  baseUrl: string;
  model: string;
  apiKey: string;
};

function loadAgentEnvFile(): Record<string, string> {
  const file = path.join(process.cwd(), "agent", ".env");
  const out: Record<string, string> = {};
  if (!existsSync(file)) return out;
  try {
    const text = readFileSync(file, "utf-8");
    for (const line of text.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq <= 0) continue;
      const key = trimmed.slice(0, eq).trim();
      let value = trimmed.slice(eq + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (key) out[key] = value;
    }
  } catch {
    /* ignore */
  }
  return out;
}

function envGet(name: string): string | undefined {
  const fromProcess = process.env[name]?.trim();
  if (fromProcess) return fromProcess;
  const fromAgent = loadAgentEnvFile()[name]?.trim();
  if (fromAgent) return fromAgent;
  return undefined;
}

export function resolveScoreVlConfig(): ScoreVlConfig {
  const baseUrl = (
    envGet("SCORE_VL_BASE_URL") ||
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
  ).replace(/\/+$/, "");
  const model = envGet("SCORE_VL_MODEL") || "qwen-vl-max";
  const apiKey =
    envGet("SCORE_VL_API_KEY") ||
    envGet("DASHSCOPE_API_KEY") ||
    envGet("SCORE_VL_API_KEYS")?.split(/[,;]/)[0]?.trim() ||
    "";
  if (!apiKey) {
    throw new Error(
      "未配置 SCORE_VL / DashScope Key。请在 .env.local 设置 SCORE_VL_API_KEY 或 DASHSCOPE_API_KEY，以及 SCORE_VL_BASE_URL / SCORE_VL_MODEL。",
    );
  }
  return { baseUrl, model, apiKey };
}

function stripFence(text: string): string {
  let t = text.trim();
  if (t.startsWith("```")) {
    t = t.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n?```$/, "").trim();
  }
  return t.replace(/^["「『]+|["」』]+$/g, "").trim();
}

const TOPIC_POOL = [
  "新品发布",
  "品牌周年",
  "行业峰会",
  "社区服务手册",
  "研学营说明",
  "公益计划",
  "城市更新提案",
  "非遗工坊",
  "智慧园区",
  "文旅路线",
  "医疗健康科普",
  "教育课程介绍",
  "零售开业",
  "体育赛事动员",
  "博物馆特展",
] as const;

/**
 * Ask SCORE_VL chat to invent one PPT topic line (content only, no style jargon).
 */
export async function generateRandomThemePrompt(options?: {
  visualStyle?: string;
  signal?: AbortSignal;
}): Promise<{ prompt: string; model: string }> {
  const cfg = resolveScoreVlConfig();
  const seed = TOPIC_POOL[Math.floor(Math.random() * TOPIC_POOL.length)];
  const salt = Math.random().toString(36).slice(2, 8);
  const styleHint = (options?.visualStyle || "").trim();

  const system = `你是 PPT 主题文案助手。只输出一段中文「主题描述」（1–3 句），不要标题、不要列表、不要引号、不要 markdown。
要求：
- 写具体内容主题（产品/活动/议题/机构），像给设计师的 brief
- 可含：对象、场合、要突出的 2–3 个要点（封面冲击力、章节、数据或收尾等）
- 禁止把视觉风格名或设计隐喻写成主题（如舞台灯光、胶印、拓扑图、代码编辑器风）
- 禁止空词：赋能、闭环、数字化转型、示意文案
- 控制在 40–90 个汉字`;

  const user = `随机种子：${seed} / ${salt}
${styleHint ? `当前选用视觉风格 id（仅供语气参考，勿写入主题文案）：${styleHint}\n` : ""}请发明一个全新的、具体的 PPT 主题描述。`;

  const url = `${cfg.baseUrl}/chat/completions`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.apiKey}`,
    },
    body: JSON.stringify({
      model: cfg.model,
      temperature: 1.1,
      max_tokens: 220,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
    }),
    signal: options?.signal,
  });

  const raw = (await res.json().catch(() => ({}))) as {
    error?: { message?: string };
    choices?: Array<{ message?: { content?: string } }>;
  };
  if (!res.ok) {
    throw new Error(
      raw.error?.message || `SCORE_VL HTTP ${res.status} @ ${cfg.model}`,
    );
  }
  const content = stripFence(String(raw.choices?.[0]?.message?.content || ""));
  if (!content) {
    throw new Error("SCORE_VL 返回空内容");
  }
  return { prompt: content, model: cfg.model };
}

const STYLE_INTENT_POOL = [
  "夜间水族馆导视",
  "法院卷宗封面",
  "蜡笔儿童绘本",
  "港式茶餐厅菜单",
  "高原天文台观测日志",
  "老式火车站时刻表",
  "植物标本册",
  "独立书店橱窗",
  "潜水日志防水便签",
  "京剧脸谱海报墙",
  "沙漠公路加油站",
  "极地科考补给清单",
  "市集手作摊位牌",
  "图书馆闭架书库",
  "城市夜跑补给站",
] as const;

/**
 * Invent a short visual-style intent (not a deck topic). Used by Admin 随机风格·发明.
 */
export async function generateRandomStyleIntent(options?: {
  signal?: AbortSignal;
}): Promise<{ intent: string; model: string }> {
  const cfg = resolveScoreVlConfig();
  const seed =
    STYLE_INTENT_POOL[Math.floor(Math.random() * STYLE_INTENT_POOL.length)];
  const salt = Math.random().toString(36).slice(2, 8);

  const system = `你是 PPT 视觉风格策划。只输出一句中文「风格意图」（8–24 字），不要标题、不要列表、不要引号、不要 markdown。
要求：
- 描述「页面长什么样」的隐喻或场景（材质/排版气质/空间意象），不是内容主题
- 例：夜间水族馆导视、蜡笔儿童绘本、法院卷宗封面
- 禁止写成产品发布会/峰会/手册等主题句
- 禁止套用已烂俗的：暗色科技、玻璃拟态、瑞士极简、霓虹赛博（除非你给出非常具体的变体）`;

  const user = `随机种子：${seed} / ${salt}
请发明一个全新的、具体的视觉风格意图。`;

  const url = `${cfg.baseUrl}/chat/completions`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.apiKey}`,
    },
    body: JSON.stringify({
      model: cfg.model,
      temperature: 1.15,
      max_tokens: 80,
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
    }),
    signal: options?.signal,
  });

  const raw = (await res.json().catch(() => ({}))) as {
    error?: { message?: string };
    choices?: Array<{ message?: { content?: string } }>;
  };
  if (!res.ok) {
    throw new Error(
      raw.error?.message || `SCORE_VL HTTP ${res.status} @ ${cfg.model}`,
    );
  }
  const content = stripFence(String(raw.choices?.[0]?.message?.content || ""));
  if (!content) {
    throw new Error("SCORE_VL 返回空风格意图");
  }
  // Keep one line, strip leftover quotes
  const intent = content
    .split(/\n/)[0]
    .replace(/^["「『]+|["」』]+$/g, "")
    .trim();
  return { intent: intent || seed, model: cfg.model };
}

/** Offline fallback when SCORE_VL is not configured. */
export function pickRandomStyleIntentSeed(): string {
  return STYLE_INTENT_POOL[
    Math.floor(Math.random() * STYLE_INTENT_POOL.length)
  ]!;
}
