import { NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";
import { assertAdmin } from "@/server/adminAuth";
import {
  llmEnvForDual,
  resolveLlmSelection,
} from "@/server/templates/llmProviders";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

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
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  };
}

/**
 * POST /api/admin/styles/ensure
 * Body: { intent: string, create?: boolean, mock?: boolean, llmProvider?, llmModel? }
 */
export async function POST(req: Request) {
  const denied = assertAdmin(req);
  if (denied) return denied;

  let body: {
    intent?: string;
    create?: boolean;
    mock?: boolean;
    llmProvider?: string;
    llmModel?: string;
  } = {};
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  const intent = String(body.intent || "").trim();
  if (!intent) {
    return NextResponse.json({ error: "INTENT_REQUIRED" }, { status: 400 });
  }
  const allowCreate = body.create !== false;
  const mock = Boolean(body.mock);

  const { cmd, cwd, env } = resolveAgentBin();
  const childEnv = { ...env };
  if (mock) childEnv.AGENT_MOCK = "1";
  if (!mock) {
    try {
      const llm = resolveLlmSelection(body.llmProvider, body.llmModel);
      Object.assign(childEnv, llmEnvForDual(llm));
      childEnv.LLM_THINKING = "0";
    } catch (e) {
      return NextResponse.json(
        { error: e instanceof Error ? e.message : String(e) },
        { status: 400 },
      );
    }
  }

  const args = ["ensure-style", "--json", intent];
  if (allowCreate) args.splice(1, 0, "--create");
  else args.splice(1, 0, "--no-create");
  if (mock) args.splice(1, 0, "--mock");

  const result = await new Promise<{
    code: number | null;
    stdout: string;
    stderr: string;
  }>((resolve) => {
    const child = spawn(cmd, args, {
      cwd,
      env: childEnv,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (c) => {
      stdout += c.toString("utf8");
    });
    child.stderr?.on("data", (c) => {
      stderr += c.toString("utf8");
    });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.on("error", (err) =>
      resolve({ code: 1, stdout: "", stderr: String(err) }),
    );
  });

  const lines = result.stdout
    .trim()
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const last = lines[lines.length - 1] || "";
  try {
    const data = JSON.parse(last) as Record<string, unknown>;
    if (result.code !== 0 || data.ok === false || data.error) {
      return NextResponse.json(
        {
          ok: false,
          error: data.error || result.stderr || "ensure_style failed",
          log: result.stderr,
        },
        { status: 400 },
      );
    }
    return NextResponse.json({ ...data, log: result.stderr });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error: result.stderr || result.stdout || "parse failed",
        code: result.code,
      },
      { status: 500 },
    );
  }
}
