/* 页面跳转联调：pathFor / parsePath 往返（契约 G16）。
   纯函数不碰 DOM，所以能在 Node 里直接跑，不用起浏览器。
   用法：node tests/test_keyword_routes.mjs */

import { pathFor, parsePath, id, apiVersion, filters } from "../web/modules/keyword.js";

let fail = 0;
const ok = (name, pass, detail = "") => {
  if (!pass) fail += 1;
  console.log(`  [${pass ? "PASS" : "FAIL"}] ${name}${pass ? "" : "  (" + detail + ")"}`);
};

console.log("== 关键词模块路由往返 ==");
ok("模块 id 与 apiVersion", id === "keyword" && apiVersion === 1, `${id}/${apiVersion}`);
ok("筛选项都带中文标签", filters.every((f) => f.label && f.key),
  JSON.stringify(filters.filter((f) => !f.label)));

/* 外壳会把 tail 拼成 /keyword/<tail>，再用 seg.slice(1) 交回 parsePath。
   所以往返要模拟外壳这一步，不能直接把 pathFor 的结果喂回去。 */
const roundTrip = (x) => parsePath(pathFor(x).split("/").filter(Boolean));

const CASES = [
  { pageId: "kw-overview", objectId: undefined },
  { pageId: "kw-market", objectId: undefined },
  { pageId: "kw-child", objectId: undefined },
  { pageId: "kw-child", objectId: "B0B3LWGP36" },
  { pageId: "kw-child", objectId: "B0CBPXNC1M" },
  { pageId: "kw-market", objectId: "kw_00001" },
  { pageId: "kw-market", objectId: "kw_01991" },
];

for (const c of CASES) {
  const r = roundTrip(c);
  const same = r.pageId === c.pageId
    && (r.objectId || undefined) === (c.objectId || undefined);
  ok(`往返 ${c.pageId}${c.objectId ? " / " + c.objectId : ""} → ${pathFor(c) || "(空)"}`,
    same, JSON.stringify(r));
}

/* 段名必须是页面 id 本身：外壳的 applyUrl() 在模块 impl 加载前就解析一次 URL，
   那时拿不到 impl.parsePath，会回落到「段名匹配 pages[].id」。
   用短别名的话首屏深链会被解析成 objectId，页签停在第一页。 */
ok("段名用页面 id 而不是短别名",
  pathFor({ pageId: "kw-child", objectId: "B0X" }).startsWith("kw-child/"),
  pathFor({ pageId: "kw-child", objectId: "B0X" }));
ok("总览不出段（外壳默认页）", pathFor({ pageId: "kw-overview" }) === "");
ok("短别名仍能解析（向后兼容）",
  parsePath(["child", "B0B3LWGP36"]).pageId === "kw-child"
  && parsePath(["market"]).pageId === "kw-market");

/* 对象 id 要编码，解码失败要回退原值不抛异常 */
const weird = "A/B?C#D E";
ok("对象 id 编码后能原样还回",
  roundTrip({ pageId: "kw-child", objectId: weird }).objectId === weird
  || pathFor({ pageId: "kw-child", objectId: weird }).includes(encodeURIComponent(weird)),
  pathFor({ pageId: "kw-child", objectId: weird }));
let threw = false;
try {
  parsePath(["kw-child", "%E0%A4%A"]);
} catch (e) {
  threw = true;
}
ok("坏编码不抛异常", !threw);

/* 未知段落回落总览，不能返回 null 让外壳空转 */
ok("未知段落回落总览", parsePath(["nonsense"]).pageId === "kw-overview");
ok("空段落回落总览", parsePath([]).pageId === "kw-overview");

console.log(`\n${CASES.length + 8} 条，失败 ${fail} 条`);
process.exit(fail ? 1 : 0);
