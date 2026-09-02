import { runDemandForecast } from "../src/demand-forecast-agent.ts";

const childAsin = (process.argv[2] ?? "B0B3LM36WB").trim().toUpperCase();
const result = await runDemandForecast({
  childAsin,
  trigger: "manual",
  fake: process.env.BAMBOO_AGENT_FAKE === "1",
  dbPath: process.env.BAMBOO_FORECAST_DB,
  exportPath: process.env.BAMBOO_FORECAST_JSON,
});

process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
if (!result.ok) process.exitCode = 1;
