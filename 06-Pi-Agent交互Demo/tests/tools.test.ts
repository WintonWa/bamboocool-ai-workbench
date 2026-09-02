import assert from "node:assert/strict";
import test from "node:test";
import { DemoRepository } from "../src/database.ts";
import { ALLOWED_TOOL_NAMES, createBusinessTools } from "../src/tools/index.ts";

test("exposes 342 child ASINs, five golden samples and a read-only database", () => {
  const repository = new DemoRepository();
  try {
    assert.equal(repository.ping(), true);
    const children = repository.listChildren();
    assert.equal(children.length, 342);
    assert.equal(children.filter((item) => item.isGoldenSample).length, 5);
    assert.equal(new Set(children.map((item) => item.analysisChildAsin)).size, 5);
    assert.throws(() => repository.db.exec("CREATE TABLE forbidden_write (id INTEGER)"));
  } finally {
    repository.close();
  }
});

test("routes non-golden ASINs explicitly to a complete golden sample", () => {
  const repository = new DemoRepository();
  try {
    const requested = repository.listChildren().find((item) => !item.isGoldenSample)!;
    const route = repository.routeDemoChildAsin(requested.childAsin);
    assert.ok(route);
    assert.equal(route.wasMapped, true);
    assert.notEqual(route.analysisChildAsin, route.requestedChildAsin);
    assert.ok(repository.getChildProductContext(route.analysisChildAsin)?.isGoldenSample);
    assert.equal(repository.routeDemoChildAsin("B000000000"), null);
  } finally {
    repository.close();
  }
});

test("returns a complete daily forecast and three inventory scenarios for every golden sample", () => {
  const repository = new DemoRepository();
  try {
    const golden = repository.listChildren().filter((item) => item.isGoldenSample);
    for (const child of golden) {
      const audit = repository.auditChildDailyHistory(child.childAsin);
      const reconstruction = repository.reconstructChildDemand(child.childAsin);
      const drivers = repository.estimateDemandDrivers(child.childAsin);
      const forecast = repository.forecastChildSalesDaily(child.childAsin);
      const supply = repository.getChildInventorySupply(child.childAsin);
      const projection = repository.projectChildInventoryDaily(child.childAsin);
      const decision = repository.recommendChildReplenishment(child.childAsin);
      assert.equal(audit?.observedDays, 730);
      assert.equal(audit?.missingDays, 0);
      assert.ok(reconstruction && reconstruction.estimatedDemandUnits >= reconstruction.observedUnits);
      assert.ok(drivers && drivers.future.plannedAdvertisingDays === 90);
      assert.equal(forecast?.horizonDays, 90);
      assert.equal(forecast?.daily.length, 90);
      assert.equal(forecast?.startDate, "2026-08-04");
      assert.equal(forecast?.endDate, "2026-11-01");
      assert.ok(forecast && forecast.p10Units <= forecast.p50Units && forecast.p50Units <= forecast.p90Units);
      assert.ok(supply && supply.asOfDate === "2026-08-03");
      assert.equal(projection?.scenarios.length, 3);
      assert.equal(projection?.dailyBase.length, 90);
      assert.ok(decision);
    }
  } finally {
    repository.close();
  }
});

test("registers exactly the nine approved Agent tools", () => {
  const repository = new DemoRepository();
  try {
    const tools = createBusinessTools(repository);
    assert.equal(tools.length, 9);
    assert.deepEqual(tools.map((tool) => tool.name), [...ALLOWED_TOOL_NAMES]);
    assert.ok(tools.every((tool) => tool.executionMode === "sequential"));
  } finally {
    repository.close();
  }
});
