const $ = (selector) => document.querySelector(selector);

const TRACE_TOOL_ORDER = [
  "route_demo_child_asin",
  "get_child_product_context",
  "audit_child_daily_history",
  "reconstruct_child_demand",
  "estimate_demand_drivers",
  "forecast_child_sales_daily",
  "get_child_inventory_supply",
  "project_child_inventory_daily",
  "recommend_child_replenishment",
];
const TRACE_RUNNING_MS = 900;
const TRACE_GAP_MS = 220;
const ANSWER_CHUNK_MS = 12;

const elements = {
  service: $("#serviceState"),
  child: $("#childSelect"),
  meta: $("#productMeta"),
  quick: $("#quickPrompt"),
  conversation: $("#conversation"),
  empty: $("#emptyState"),
  form: $("#composer"),
  input: $("#messageInput"),
  send: $("#sendButton"),
  stop: $("#stopButton"),
  retry: $("#retryButton"),
  clear: $("#clearButton"),
  live: $("#live-agent-demo"),
  glassStage: $(".glass-stage"),
};

const state = {
  children: [],
  sessionId: makeSessionId(),
  controller: null,
  running: false,
  lastRequest: null,
  currentTurn: null,
};

function makeSessionId() {
  return `session_${crypto.randomUUID()}`;
}

function setupPageEffects() {
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  for (const trigger of document.querySelectorAll("[data-scroll-to-agent]")) {
    trigger.addEventListener("click", () => {
      elements.live?.scrollIntoView({ behavior: prefersReducedMotion.matches ? "auto" : "smooth", block: "start" });
      window.setTimeout(() => elements.input.focus({ preventScroll: true }), prefersReducedMotion.matches ? 0 : 620);
    });
  }

  if (!elements.glassStage || !window.matchMedia("(pointer: fine)").matches) return;

  elements.glassStage.addEventListener("pointermove", (event) => {
    if (prefersReducedMotion.matches) return;
    const bounds = elements.glassStage.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
    const y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
    elements.glassStage.style.setProperty("--pointer-x", `${(x * 100).toFixed(1)}%`);
    elements.glassStage.style.setProperty("--pointer-y", `${(y * 100).toFixed(1)}%`);
    elements.glassStage.style.setProperty("--tilt-x", `${((.5 - y) * 5).toFixed(2)}deg`);
    elements.glassStage.style.setProperty("--tilt-y", `${((x - .5) * 6).toFixed(2)}deg`);
  });

  elements.glassStage.addEventListener("pointerleave", () => {
    elements.glassStage.style.setProperty("--pointer-x", "50%");
    elements.glassStage.style.setProperty("--pointer-y", "48%");
    elements.glassStage.style.setProperty("--tilt-x", "0deg");
    elements.glassStage.style.setProperty("--tilt-y", "0deg");
  });
}

function text(tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function setService(kind, label) {
  elements.service.className = `service-state ${kind}`;
  elements.service.querySelector("b").textContent = label;
}

function setRunning(running) {
  state.running = running;
  elements.send.disabled = running || !state.children.length;
  elements.child.disabled = running || !state.children.length;
  elements.stop.hidden = !running;
  elements.retry.disabled = running || !state.lastRequest;
  elements.input.disabled = running;
}

function renderProduct() {
  const product = state.children.find((item) => item.childAsin === elements.child.value);
  elements.meta.replaceChildren();
  if (!product) return;
  const items = [
    ["父 ASIN", product.parentAsin],
    ["尺码", product.size || "未标注"],
    ["生命周期", product.lifecycleStage],
    ["演示画像", product.profileName],
  ];
  for (const [label, value] of items) {
    const box = document.createElement("div");
    box.append(text("span", "", label), text("strong", "", value));
    elements.meta.append(box);
  }
}

async function bootstrap() {
  try {
    const [healthResponse, childResponse] = await Promise.all([fetch("/api/health"), fetch("/api/children")]);
    if (!healthResponse.ok || !childResponse.ok) throw new Error("service unavailable");
    const health = await healthResponse.json();
    const payload = await childResponse.json();
    state.children = payload.children || [];
    elements.child.replaceChildren(...state.children.map((item) => {
      const option = document.createElement("option");
      option.value = item.childAsin;
      option.textContent = `${item.isGoldenSample ? "★ " : ""}${item.childAsin} · ${item.styleName} · ${item.size}`;
      return option;
    }));
    renderProduct();
    setService(health.piConfigured ? "ready" : "error", health.piConfigured ? "本地 Pi 与数据已就绪" : "Pi 尚未完成本机配置");
    setRunning(false);
  } catch {
    setService("error", "本地 Agent 服务不可用");
    elements.child.replaceChildren(new Option("无法加载子 ASIN", ""));
  }
}

function addUserMessage(message) {
  elements.empty?.remove();
  const wrap = text("article", "message user");
  wrap.append(text("span", "message-label", "你"), text("div", "user-bubble", message));
  elements.conversation.append(wrap);
}

function createAgentTurn() {
  const wrap = text("article", "message agent");
  wrap.append(text("span", "message-label", "Bamboo Agent"));
  const card = text("div", "agent-turn");
  const status = text("div", "run-status");
  status.append(text("span", "pulse"), text("span", "status-copy", "准备调用 Pi Agent…"));
  const trace = text("div", "trace");
  const toggle = text("button", "trace-toggle");
  toggle.type = "button";
  toggle.append(text("span", "", "执行过程"), text("span", "trace-count", "0 个步骤"));
  const list = text("ol", "trace-list");
  trace.append(toggle, list);
  toggle.addEventListener("click", () => trace.classList.toggle("collapsed"));
  const warningArea = text("div", "warning-area");
  const answer = text("div", "answer");
  card.append(status, trace, warningArea, answer);
  wrap.append(card);
  elements.conversation.append(wrap);
  elements.conversation.scrollTop = elements.conversation.scrollHeight;
  return { wrap, card, status, statusCopy: status.querySelector(".status-copy"), trace, list, count: toggle.querySelector(".trace-count"), warningArea, answer, steps: new Map() };
}

function updateStep(turn, event) {
  let item = turn.steps.get(event.stepId);
  if (!item) {
    item = text("li", "trace-item running");
    const icon = text("span", "step-icon");
    const copy = text("div", "step-copy");
    copy.append(text("strong", "", event.label || "执行业务工具"), text("small", "", "执行中…"));
    item.append(icon, copy, text("span", "step-time", ""));
    turn.steps.set(event.stepId, item);
    turn.list.append(item);
  }
  if (event.type === "step.completed" || event.type === "step.failed") {
    item.className = `trace-item ${event.type === "step.failed" ? "failed" : "complete"}`;
    item.querySelector("small").textContent = event.summary || (event.type === "step.failed" ? "执行失败" : "执行完成");
    item.querySelector(".step-time").textContent = typeof event.durationMs === "number" ? `${event.durationMs}ms` : "";
  }
  turn.count.textContent = `${turn.steps.size} 个步骤`;
}

function addWarning(turn, message) {
  turn.warningArea.append(text("div", "run-warning", message));
}

function handleEvent(turn, event) {
  if (event.type === "run.started") turn.statusCopy.textContent = "Agent 正在分析…";
  else if (event.type.startsWith("step.")) {
    updateStep(turn, event);
    turn.statusCopy.textContent = event.type === "step.started" ? event.label : "继续分析工具结果…";
  } else if (event.type === "answer.delta") {
    turn.answer.textContent += event.delta || "";
    turn.statusCopy.textContent = "正在生成结论…";
  } else if (event.type === "run.warning") addWarning(turn, event.message || "本次运行有一项提示。");
  else if (event.type === "run.completed") {
    turn.status.classList.add("complete");
    turn.statusCopy.textContent = "分析完成";
  } else if (event.type === "run.failed") {
    turn.status.classList.add("error");
    turn.statusCopy.textContent = event.message || "Agent 运行失败";
    if (!turn.answer.textContent) turn.answer.textContent = event.message || "Agent 运行失败，请重试。";
  } else if (event.type === "run.cancelled") {
    turn.status.classList.add("error");
    turn.statusCopy.textContent = "已停止";
  }
  elements.conversation.scrollTop = elements.conversation.scrollHeight;
}

async function readNdjson(response, turn) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let playback = Promise.resolve();
  let nextToolIndex = 0;
  const startedByTool = new Map();
  const completedByTool = new Map();

  const enqueue = (event, waitAfter = 0) => {
    playback = playback.then(async () => {
      handleEvent(turn, event);
      if (waitAfter) await sleep(waitAfter);
    });
  };

  const flushCompletedSteps = () => {
    while (nextToolIndex < TRACE_TOOL_ORDER.length) {
      const tool = TRACE_TOOL_ORDER[nextToolIndex];
      const completed = completedByTool.get(tool);
      if (!completed) break;
      const started = startedByTool.get(tool) || {
        type: "step.started",
        runId: completed.runId,
        stepId: completed.stepId,
        tool,
        label: completed.label,
      };
      enqueue(started, TRACE_RUNNING_MS);
      enqueue(completed, TRACE_GAP_MS);
      startedByTool.delete(tool);
      completedByTool.delete(tool);
      if (completed.type === "step.failed") break;
      nextToolIndex += 1;
    }
  };

  const queueEvent = (event) => {
    if (event.type === "run.started") {
      handleEvent(turn, event);
    } else if (event.type === "step.started") {
      startedByTool.set(event.tool, event);
    } else if (event.type === "step.completed" || event.type === "step.failed") {
      completedByTool.set(event.tool, event);
      flushCompletedSteps();
    } else {
      enqueue(event, event.type === "answer.delta" ? ANSWER_CHUNK_MS : 0);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) if (line.trim()) queueEvent(JSON.parse(line));
    if (done) break;
  }
  if (buffer.trim()) queueEvent(JSON.parse(buffer));
  await playback;
}

async function runAgent(request, { repeat = false } = {}) {
  if (state.running) return;
  state.lastRequest = request;
  if (!repeat) addUserMessage(request.message);
  const turn = createAgentTurn();
  state.currentTurn = turn;
  state.controller = new AbortController();
  setRunning(true);
  try {
    const response = await fetch("/api/agent/run", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...request, sessionId: state.sessionId, scenarioId: "forecast-child-sales-inventory-90d" }),
      signal: state.controller.signal,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.message || "本地 Agent 请求失败。");
    }
    await readNdjson(response, turn);
  } catch (error) {
    if (error.name === "AbortError") {
      turn.status.classList.add("error");
      turn.statusCopy.textContent = "已停止";
      if (!turn.answer.textContent) turn.answer.textContent = "本次运行已由你停止。";
    } else {
      turn.status.classList.add("error");
      turn.statusCopy.textContent = "运行失败";
      if (!turn.answer.textContent) turn.answer.textContent = error.message || "本地 Agent 服务不可用。";
    }
  } finally {
    state.controller = null;
    setRunning(false);
    elements.input.focus();
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = elements.input.value.trim();
  const childAsin = elements.child.value;
  if (!message || !childAsin || state.running) return;
  elements.input.value = "";
  runAgent({ childAsin, message });
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});

elements.child.addEventListener("change", renderProduct);
elements.quick.addEventListener("click", () => {
  elements.input.value = elements.quick.textContent.trim();
  elements.input.focus();
});
elements.stop.addEventListener("click", () => state.controller?.abort());
elements.retry.addEventListener("click", () => state.lastRequest && runAgent(state.lastRequest, { repeat: true }));
elements.clear.addEventListener("click", async () => {
  state.controller?.abort();
  const oldSession = state.sessionId;
  state.sessionId = makeSessionId();
  state.lastRequest = null;
  elements.retry.disabled = true;
  elements.conversation.replaceChildren();
  const empty = text("div", "empty-state");
  empty.append(text("span", "empty-orb"), text("h2", "", "问一个固定场景的问题"), text("p", "", "你会看到 Agent 实际查了什么、计算了什么，以及最后如何形成答案。"));
  elements.conversation.append(empty);
  await fetch(`/api/agent/session/${encodeURIComponent(oldSession)}`, { method: "DELETE" }).catch(() => {});
});

setupPageEffects();
bootstrap();
