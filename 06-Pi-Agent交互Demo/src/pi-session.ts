import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  type AgentSession,
} from "@earendil-works/pi-coding-agent";
import type { DemoRepository } from "./database.ts";
import { MAX_SESSIONS, ROOT_DIR, SESSION_TTL_MS, SKILL_DIR } from "./config.ts";
import { SYSTEM_PROMPT } from "./scenarios/index.ts";
import { ALLOWED_TOOL_NAMES, createBusinessTools } from "./tools/index.ts";

type StoredSession = {
  session: AgentSession;
  workflow: SequentialToolWorkflow;
  lastUsedAt: number;
  busy: boolean;
};

type WorkflowSession = Pick<AgentSession, "setActiveToolsByName" | "subscribe">;

export type SequentialToolWorkflow = {
  reset: () => void;
  dispose: () => void;
  expectedTool: () => string | null;
};

let sharedModelRuntime: Promise<ModelRuntime> | undefined;

function modelRuntime(): Promise<ModelRuntime> {
  sharedModelRuntime ??= ModelRuntime.create();
  return sharedModelRuntime;
}

export function attachSequentialToolWorkflow(session: WorkflowSession): SequentialToolWorkflow {
  let stepIndex = 0;

  const exposeExpectedTool = () => {
    const toolName = ALLOWED_TOOL_NAMES[stepIndex];
    session.setActiveToolsByName(toolName ? [toolName] : []);
  };

  const unsubscribe = session.subscribe((event) => {
    if (event.type !== "tool_execution_end" || event.isError) return;
    if (event.toolName !== ALLOWED_TOOL_NAMES[stepIndex]) return;
    stepIndex += 1;
    exposeExpectedTool();
  });

  exposeExpectedTool();
  return {
    reset: () => {
      stepIndex = 0;
      exposeExpectedTool();
    },
    dispose: unsubscribe,
    expectedTool: () => ALLOWED_TOOL_NAMES[stepIndex] ?? null,
  };
}

async function createRestrictedSession(repository: DemoRepository): Promise<{ session: AgentSession; workflow: SequentialToolWorkflow }> {
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(ROOT_DIR, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: ROOT_DIR,
    agentDir,
    settingsManager,
    noExtensions: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    additionalSkillPaths: [SKILL_DIR],
    skillsOverride: (current) => ({
      skills: current.skills.filter((skill) => skill.name === "forecast-child-90d"),
      diagnostics: current.diagnostics,
    }),
    systemPromptOverride: () => SYSTEM_PROMPT,
    appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  if (!loader.getSkills().skills.some((skill) => skill.name === "forecast-child-90d")) {
    throw new Error("child forecast skill unavailable");
  }
  const { session } = await createAgentSession({
    cwd: ROOT_DIR,
    agentDir,
    modelRuntime: await modelRuntime(),
    thinkingLevel: "low",
    tools: [...ALLOWED_TOOL_NAMES],
    customTools: createBusinessTools(repository),
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(ROOT_DIR),
    settingsManager,
  });
  const workflow = attachSequentialToolWorkflow(session);
  const activeTools = session.getActiveToolNames();
  if (activeTools.length !== 1 || activeTools[0] !== ALLOWED_TOOL_NAMES[0]) {
    workflow.dispose();
    session.dispose();
    throw new Error("restricted tool allowlist mismatch");
  }
  return { session, workflow };
}

export class PiSessionStore {
  private readonly sessions = new Map<string, StoredSession>();
  private readonly repository: DemoRepository;

  constructor(repository: DemoRepository) {
    this.repository = repository;
  }

  async getOrCreate(sessionId: string): Promise<StoredSession> {
    this.cleanupExpired();
    const existing = this.sessions.get(sessionId);
    if (existing) {
      existing.lastUsedAt = Date.now();
      return existing;
    }
    while (this.sessions.size >= MAX_SESSIONS) this.evictOldest();
    const { session, workflow } = await createRestrictedSession(this.repository);
    const created = { session, workflow, lastUsedAt: Date.now(), busy: false };
    this.sessions.set(sessionId, created);
    return created;
  }

  delete(sessionId: string): boolean {
    const stored = this.sessions.get(sessionId);
    if (!stored) return false;
    if (stored.busy) void stored.session.abort();
    stored.workflow.dispose();
    stored.session.dispose();
    this.sessions.delete(sessionId);
    return true;
  }

  disposeAll(): void {
    for (const stored of this.sessions.values()) {
      stored.workflow.dispose();
      stored.session.dispose();
    }
    this.sessions.clear();
  }

  private cleanupExpired(): void {
    const cutoff = Date.now() - SESSION_TTL_MS;
    for (const [id, stored] of this.sessions) {
      if (!stored.busy && stored.lastUsedAt < cutoff) this.delete(id);
    }
  }

  private evictOldest(): void {
    const candidate = [...this.sessions.entries()]
      .filter(([, stored]) => !stored.busy)
      .sort((a, b) => a[1].lastUsedAt - b[1].lastUsedAt)[0];
    if (!candidate) throw new Error("all sessions are busy");
    this.delete(candidate[0]);
  }
}
