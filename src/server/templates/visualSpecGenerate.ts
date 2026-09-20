/**
 * 调用 webppt-agent 为模板包生成 visual-spec.md。
 */

import { access, copyFile } from "fs/promises";
import path from "path";
import { spawn } from "child_process";
import { TEMPLATES_ROOT } from "@/server/htmlTemplates";
import {
  llmEnvForDual,
  resolveLlmSelection,
} from "@/server/templates/llmProviders";

export type VisualSpecGenerateResult = {
  path: string;
  log: string;
};

async function pathExists(p: string): Promise<boolean> {
  try {
    await access(p);
    return true;
  } catch {
    return false;
  }
}

function resolveAgentBin(): { cmd: string; cwd: string } {
  const agentDir = path.resolve(process.cwd(), "agent");
  const venvBin =
    process.platform === "win32"
      ? path.join(agentDir, ".venv", "Scripts", "webppt-agent.exe")
      : path.join(agentDir, ".venv", "bin", "webppt-agent");
  return { cmd: venvBin, cwd: agentDir };
}

function runAgent(
  cmd: string,
  args: string[],
  opts: { cwd: string; env: NodeJS.ProcessEnv }
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd: opts.cwd,
      env: opts.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (buf: Buffer) => {
      stdout += buf.toString("utf8");
    });
    child.stderr?.on("data", (buf: Buffer) => {
      stderr += buf.toString("utf8");
    });
    child.on("error", (err) => {
      resolve({ code: 1, stdout, stderr: `${stderr}\n${err.message}` });
    });
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

/**
 * 在本地 agent-output/<id>/ 生成 / 覆盖 visual-spec.md（用未压缩 theme 供 LLM）。
 */
export async function generateVisualSpecMd(
  id: string,
  opts?: { mock?: boolean }
): Promise<VisualSpecGenerateResult> {
  const packageDir = path.join(TEMPLATES_ROOT, id);
  if (!(await pathExists(path.join(packageDir, "template.json")))) {
    throw new Error(`模板不存在: ${id}`);
  }

  const { cmd, cwd } = resolveAgentBin();
  if (!(await pathExists(cmd))) {
    throw new Error(
      `未找到 webppt-agent：${cmd}。请先在 agent/ 下创建 venv 并 pip install -e .`
    );
  }

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
  };
  if (!opts?.mock) {
    const heavy = resolveLlmSelection();
    // visual-spec is a compact documentation task; allow the agent's light
    // model routing instead of forcing a second heavy-model call.
    Object.assign(env, llmEnvForDual(heavy));
  }

  const args = ["visual-spec", packageDir];
  if (opts?.mock) args.push("--mock");

  const result = await runAgent(cmd, args, { cwd, env });
  if (result.code !== 0) {
    throw new Error(
      (result.stderr || result.stdout || "visual-spec 生成失败").trim()
    );
  }

  const specPath = path.join(packageDir, "visual-spec.md");
  if (!(await pathExists(specPath))) {
    throw new Error("visual-spec 生成成功但未找到 visual-spec.md");
  }

  return {
    path: `agent-output/${id}/visual-spec.md`,
    log: (result.stdout || "").trim(),
  };
}

/** 把本地 visual-spec.md 拷进打包工作目录（覆盖） */
export async function copyVisualSpecIntoWorkDir(
  id: string,
  workDir: string
): Promise<void> {
  const src = path.join(TEMPLATES_ROOT, id, "visual-spec.md");
  if (!(await pathExists(src))) {
    throw new Error("缺少 visual-spec.md，无法打入压缩包");
  }
  await copyFile(src, path.join(workDir, "visual-spec.md"));
}
