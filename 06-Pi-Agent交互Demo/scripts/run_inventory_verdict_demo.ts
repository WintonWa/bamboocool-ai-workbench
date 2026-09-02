import {
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  getAgentDir,
  ModelRuntime,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import {
  DEFAULT_EXPORT_JSON,
  DEFAULT_VERDICT_DB,
  loadVerdictFacts,
  PROJECT_ROOT,
  validateVerdictItems,
  writeVerdictRun,
  type VerdictFacts,
  type VerdictItem,
} from "../src/inventory-verdict.ts";

const childAsin = (process.argv[2] ?? "B0B3LM36WB").trim().toUpperCase();
let loadedFacts: VerdictFacts | undefined;
let persisted: ReturnType<typeof writeVerdictRun> | undefined;
let modelVersion = "pi-local-default";

const itemSchema = Type.Object({
  block: Type.Union([
    Type.Literal("safety"), Type.Literal("stockout"), Type.Literal("in_transit"),
    Type.Literal("overstock"), Type.Literal("storage_fee"),
  ]),
  ord: Type.Integer({ minimum: 1, maximum: 5 }),
  state: Type.String(),
  verdict: Type.String(),
  because: Type.Union([Type.String(), Type.Null()]),
  refs: Type.Array(Type.String()),
  numbers: Type.Record(Type.String(), Type.Unknown()),
});

const tools = [
  defineTool({
    name: "get_inventory_verdict_facts",
    label: "读取库存结论事实",
    description: "从工作台同一套计算逻辑读取指定子 ASIN 的需求、库存、在途、库龄、仓储费和契约数字。",
    executionMode: "sequential",
    parameters: Type.Object({ child_asin: Type.String() }),
    execute: async (_id, params) => {
      loadedFacts = loadVerdictFacts(params.child_asin);
      process.stderr.write(`[1/2] 已读取 ${loadedFacts.child_asin} 的页面同口径事实\n`);
      return { content: [{ type: "text" as const, text: JSON.stringify(loadedFacts) }], details: loadedFacts };
    },
  }),
  defineTool({
    name: "submit_inventory_verdict_contract",
    label: "校验并写入库存结论",
    description: "提交五条结论契约；校验状态、顺序、引用和数字后，原子写入前端结论库并导出 JSON。",
    executionMode: "sequential",
    parameters: Type.Object({ child_asin: Type.String(), items: Type.Array(itemSchema, { minItems: 5, maxItems: 5 }) }),
    execute: async (_id, params) => {
      if (!loadedFacts) {
        return { isError: true, content: [{ type: "text" as const, text: "请先调用 get_inventory_verdict_facts" }], details: { ok: false } };
      }
      if (params.child_asin.trim().toUpperCase() !== loadedFacts.child_asin) {
        return { isError: true, content: [{ type: "text" as const, text: "child_asin 与读取事实不一致" }], details: { ok: false } };
      }
      const items = params.items as VerdictItem[];
      const errors = validateVerdictItems(loadedFacts, items);
      if (errors.length) {
        return {
          isError: true,
          content: [{ type: "text" as const, text: JSON.stringify({ ok: false, errors }) }],
          details: { ok: false, errors },
        };
      }
      persisted = writeVerdictRun(loadedFacts, items, modelVersion, DEFAULT_VERDICT_DB, DEFAULT_EXPORT_JSON);
      process.stderr.write(`[2/2] 契约校验通过并写入 ${persisted.run.run_id}\n`);
      return { content: [{ type: "text" as const, text: JSON.stringify({ ok: true, ...persisted }) }], details: { ok: true, ...persisted } };
    },
  }),
];

const SYSTEM_PROMPT = `你是 Bamboocool 库存盘点结论 Agent。你的任务不是重新计算数字，而是把工具提供的同页事实压缩成前端可消费的五条契约结论。

严格流程：
1. 用户要求“第一步”时，只调用 get_inventory_verdict_facts，工具返回后立即结束该轮，绝不尝试第二个工具。
2. 用户要求“第二步”时，只调用 submit_inventory_verdict_contract，不输出中间答案。
3. 必须提交 safety、in_transit、stockout、overstock、storage_fee 五条，ord 依次为 1 到 5。
4. state、refs、numbers 必须逐字复制对应 contract_facts；不得重新计算、删字段或改数字。
5. verdict 是 160 字内的一句话，只允许一个句末标点；because 说明依据与业务含义。
6. 在途只判断正常、来不及或无在途；没有实收事实时绝不声称有逾期。
7. 禁止免责声明、英文内部枚举和虚构行动结果。
提交工具若返回校验错误，按错误修正后再次提交。`;

async function main() {
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(PROJECT_ROOT, agentDir);
  const loader = new DefaultResourceLoader({
    cwd: PROJECT_ROOT,
    agentDir,
    settingsManager,
    noExtensions: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
    systemPromptOverride: () => SYSTEM_PROMPT,
    appendSystemPromptOverride: () => [],
  });
  await loader.reload();
  const { session } = await createAgentSession({
    cwd: PROJECT_ROOT,
    agentDir,
    modelRuntime: await ModelRuntime.create(),
    thinkingLevel: "low",
    tools: ["get_inventory_verdict_facts", "submit_inventory_verdict_contract"],
    customTools: tools,
    resourceLoader: loader,
    sessionManager: SessionManager.inMemory(PROJECT_ROOT),
    settingsManager,
  });
  const model = session.model;
  if (model) modelVersion = `${model.provider}/${model.id}`;
  const names = ["get_inventory_verdict_facts", "submit_inventory_verdict_contract"] as const;
  const unsubscribe = session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      process.stderr.write(event.assistantMessageEvent.delta);
    }
  });
  try {
    process.stderr.write(`Pi Agent 开始生成 ${childAsin} 的库存结论契约（模型 ${modelVersion}）\n`);
    // 两轮而不是赌模型会在一个 response 里连续调用两个工具：先取事实，
    // 编排器确认成功后才开放提交工具。这与生产中的“结果评估 -> 下一步”一致。
    session.setActiveToolsByName([names[0]]);
    await session.prompt(`第一步：只为子 ASIN ${childAsin} 调用事实读取工具；工具返回后立即结束本轮，不要尝试提交。`);
    if (!loadedFacts) throw new Error("Pi Agent 未完成库存事实读取");
    session.setActiveToolsByName([names[1]]);
    await session.prompt(`第二步：现在必须调用当前唯一可用的 submit_inventory_verdict_contract 工具。child_asin 为 ${childAsin}；根据上一轮工具返回的 contract_facts 生成五条 items。不要回答解释文字，唯一合法响应是工具调用。`);
    if (!persisted) throw new Error("Pi Agent 未完成契约提交");
    process.stdout.write(`${JSON.stringify(persisted, null, 2)}\n`);
  } finally {
    unsubscribe();
    session.dispose();
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}\n`);
  process.exitCode = 1;
});
