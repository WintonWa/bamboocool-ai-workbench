"""外壳任务面板要的运行过程（`MODULE["tasks"]` 的 run / poll 路由）。

外壳的契约（`web/shell.js` 第 534 行起）：
  声明 `{ id, label, needs?, run, poll?, hint? }`
  run 路由回 `{ steps: [...], run: {...} }`，外壳按 220ms 逐步揭示
  每步 `{ label, status, detail?, sources? }`，status 用中文状态词表

这里做的是**把已落库的一次真实运行还原成过程**，不是现场跑 Agent——
Agent 由本地 Runner 跑（浏览器拿不到请求体，外壳也不代跑）。所以：

* 已经跑过 → 逐步显示那次运行真实的十回合，耗时与条数都是真值
* 还没跑过 → 步骤全部「待确认」，并说明要在本地执行 Runner
* 结果过期 → 步骤停在「依据已变」那一步

**不编造进度**：每步的条数来自 `fact_ads_agent_output` 的真实行数，
不是按固定节奏播的动画。外壳那 220ms 只是揭示节奏，显示的值是真的。
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from . import agent_result

# 本地 Runner。工作台起子进程触发它，实测它会回调
# /api/ads/context 拿干净事实，所以两侧 hash 天然一致。
RUNNER_DIR = Path("/Users/linsen/BAM/06-Pi-Agent交互Demo")
RUNNER = RUNNER_DIR / "scripts" / "run_ads_agent_demo.ts"
LOG_DIR = Path(__file__).resolve().parent / "derived"
DB = LOG_DIR / "ads_agent_state.sqlite"
NODE = "node"


def _log_path(child_asin: str) -> Path:
    return LOG_DIR / ("runner-%s.log" % child_asin)


def trigger(child_asin: str) -> dict:
    """起一次真实 Runner。不等它跑完——一回合就可能 90 秒，外壳会轮 poll。

    刻意不吞异常：Runner 不在、node 没装、模型没余额，都要如实报上去。
    demo 里「看起来跑了其实没跑」比「明确失败」危险得多。
    """
    if not RUNNER.is_file():
        return {"ok": False, "message": "找不到本地 Runner：%s" % RUNNER}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = _log_path(child_asin)
    log.write_text("")            # 清掉上一次的输出，免得旧报错被当成本次的
    try:
        with open(log, "wb") as fh:
            subprocess.Popen(
                [NODE, str(RUNNER), child_asin],
                cwd=str(RUNNER_DIR), stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True,      # 脱离工作台的进程组，别被一起收走
            )
    except FileNotFoundError:
        return {"ok": False, "message": "起不了 node，本机可能没装或不在 PATH"}
    except OSError as e:                                      # noqa: BLE001
        return {"ok": False, "message": "起 Runner 失败：%s" % e}
    rid = _mark_running(child_asin)
    return {"ok": True, "message": "已触发本地 Runner，正在跑", "run_id": rid}


def _mark_running(child_asin: str) -> str | None:
    """记一个「本次触发」的标记，供外壳识别新运行。

    外壳判「开跑没有」的判据是**状态接口里出现新的 run_id**
    （shell.js 的 pollTask 拿起跑前的 id 做对比）。Runner 要几十秒才写
    第一行结果，中间这段外壳会判「没有开跑」然后停止跟踪。

    第一版想往 `fact_ads_agent_run` 插一行 status='running' 占位，
    但那张表几乎每列都是 NOT NULL——它的设计就是「只记完整运行」，
    硬塞占位行是在破坏 Agent 侧的表约定。改成写自己的一个小文件，
    只用来生成一个本次触发的 id，不碰他的表。
    """
    rid = "%s-trigger-%s" % (child_asin, time.strftime("%Y%m%d%H%M%S"))
    try:
        (LOG_DIR / ("trigger-%s.id" % child_asin)).write_text(rid)
        return rid
    except OSError:
        return None


def trigger_id(child_asin: str) -> str | None:
    """本次触发的标记 id。Runner 落下真 run 之后就不用它了。"""
    f = LOG_DIR / ("trigger-%s.id" % child_asin)
    try:
        return f.read_text().strip() or None
    except OSError:
        return None


def runner_progress(child_asin: str) -> int:
    """Runner 跑到第几步。它自己就在打 [3/10]、[6/10] 这种步号。

    必须读整个日志文件，不能读 runner_tail —— 那个只取尾巴几行，
    步号早被挤出去了（实测读成 0）。
    """
    try:
        txt = _log_path(child_asin).read_text(errors="replace")
    except OSError:
        return 0
    return max((int(m) for m in re.findall(r"\[(\d+)/10\]", txt)), default=0)


def runner_run_id(child_asin: str) -> str | None:
    """本次 Runner 自己报的 run_id，从它的日志里读。

    日志在每次触发时清空，所以里面出现的 run_id 一定属于这一次运行。
    先前用「触发时刻 vs 落库完成时刻」比大小来猜，两次运行叠在一起时
    会把上一次的结果认成这次的——直接读它自己报的 id 就没有这个问题。
    """
    log = _log_path(child_asin)
    try:
        txt = log.read_text(errors="replace")
    except OSError:
        return None
    hits = re.findall(r"run_id: ([A-Za-z0-9_.\-]+)", txt)
    return hits[-1] if hits else None


def reported_run_id(child_asin: str, res: dict) -> tuple[str | None, bool]:
    """报给外壳的 run_id，以及这次触发是否还在飞。

    外壳判「开跑没有」的办法是：起跑前先读一次 run_id 当基线，之后要求
    这个 id 变掉（见 shell.js 的 pollTask）。所以对**已经跑过**的对象，
    只要我一直回那条旧的 completed run_id，外壳就永远判「没有开跑」——
    截图上那句红字就是这么来的。

    判据：本次 Runner 报的 id 和落库那条一致，才算这次的结果已经到位；
    否则这次还在飞，回触发标记（一个外壳没见过的新 id）让它继续轮。
    """
    tid = trigger_id(child_asin)
    if not tid:
        return res.get("run_id"), False
    mine = runner_run_id(child_asin)
    landed = res.get("run_id")
    if mine and landed and mine == landed:
        return landed, False               # 落库的正是这次跑出来的
    return tid, True                        # 这次还在飞


def runner_tail(child_asin: str, n: int = 12) -> list[str]:
    """Runner 的最后几行输出。它自己会打 [1/10] 这种进度，
    模型报错也在里面——比只说「失败」有用得多。"""
    log = _log_path(child_asin)
    if not log.is_file():
        return []
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError:
        return []
    keep = [x.strip() for x in lines
            if x.strip() and not x.startswith("(node:")]
    return keep[-n:]


def running(child_asin: str) -> bool:
    """Runner 还在跑吗。

    第一版按日志最后修改时间判（120 秒内算在跑），结果 Runner 已经报错退出
    还显示「运行中」——按时间判活对一个已经死掉的进程永远是错的。
    改成看日志里有没有终止信号：报错行或完成行出现就算结束。
    """
    tail = runner_tail(child_asin, 40)
    if not tail:
        return False
    blob = "\n".join(tail)
    dead = ("Error:" in blob or "错误" in blob or "Traceback" in blob
            or "已提交" in blob or "运行完成" in blob or "commit" in blob
            and "调用成功" in blob)
    if dead:
        return False
    log = _log_path(child_asin)
    try:
        # 没有终止信号，再看它有没有还在写
        return (time.time() - log.stat().st_mtime) < 120
    except OSError:
        return False


def runner_failed(child_asin: str) -> str | None:
    """Runner 自己报的错。有就原样带上屏——比「失败」有用得多。"""
    for line in reversed(runner_tail(child_asin, 40)):
        if line.startswith("Error:") or "错误" in line:
            return line[:180]
    return None

# 十回合：一步输入桥 + 八个输出点 + 一步全链校验。
# label 是上屏文案，sources 用中文数据源名（表名不上屏，契约 G9）。
LOOP = [
    ("input", "读取干净事实", None,
     ["运营设定的产品目标", "库存与在途", "销量历史", "广告表现",
      "关键词位置", "竞品市场"]),
    ("B0b", "判断目标约束分档", "B0b", ["产品目标", "库存承接", "成本与流量"]),
    ("B0cd", "判断词与竞品", "B0cd", ["关键词位置", "竞品市场"]),
    ("B0e", "识别结构问题", "B0e", ["广告对象与产品关系"]),
    ("B1", "推导应有广告任务", "B1", ["前三步结果", "产品目标"]),
    ("B2", "对照任务与现有结构", "B2", ["应有任务", "现有广告结构"]),
    ("B3", "形成诊断与优先级", "B3", ["任务对照", "广告表现"]),
    ("B3b", "逐类核对十类问题", "B3b", ["诊断结果"]),
    ("B4", "生成调整方案", "B4", ["诊断结果", "目标约束"]),
    ("gate", "全链路校验", None,
     ["词表", "依据目录", "数字口径", "跨步引用"]),
]


def _count(res: dict, point: str | None) -> int:
    if not point:
        return 0
    return len((res.get("points") or {}).get(point) or [])


def steps(res: dict) -> list[dict]:
    """把一次运行还原成十步。条数是真实落库行数。"""
    done = bool(res.get("run_id"))
    pending = set(res.get("pending_points") or [])
    out = []
    for _sid, label, point, sources in LOOP:
        if not done:
            status, detail = "待确认", None
        elif point and point in pending:
            status, detail = "缺失", "这一步本次运行没有产出"
        elif point:
            n = _count(res, point)
            status = "正常" if n else "缺失"
            detail = "产出 %d 条" % n if n else "没有产出"
        else:
            # 输入桥与全链校验没有输出点，跟着整次运行的状态走
            status = "正常" if res.get("condition") == "正常" else "待确认"
            detail = None
        out.append({"label": label, "status": status,
                    "detail": detail, "sources": sources})
    return out


def task_run_a1() -> dict:
    """A1 广告目的标签判断的批量结果。按广告对象跑，不按子 ASIN。

    这一步的「过程」是覆盖面而不是链条：跑了多少对象、多少条建议、
    多少条无法识别。无法识别不是失败——方案 3.4 明写那是要演的状态。
    """
    res = agent_result.latest_purpose_labels()
    by = res.get("by_object") or {}
    ran = bool(by)
    items = [x for v in by.values() for x in (v.get("items") or [])]
    unrec = len([x for x in items
                 if x.get("confirmation_status") == "unrecognized"])
    with_reason = len([x for x in items if (x.get("rationale") or "").strip()])
    model = next((v.get("model_version") for v in by.values()
                  if v.get("model_version")), None)
    latest_at = max((v.get("created_at") or "" for v in by.values()),
                    default="")

    def step(label, status, detail=None, sources=None):
        return {"label": label, "status": status,
                "detail": detail, "sources": sources}

    if not ran:
        st = [step(x, "待确认", None, s) for x, s in (
            ("读取广告对象事实", ["广告对象名称与类型", "投放对象内容",
                            "运营已有记录"]),
            ("判断广告目的标签", ["命名线索", "投放内容"]),
            ("契约校验", ["词表", "确认状态"]),
            ("按对象落库", None))]
        return {"steps": st, "run": {
            "status": "待确认",
            # 说实话：A1 不是「你没跑」，是 Agent 侧还没有驱动 A1 的脚本
            # （ADS_OUTPUT_POINTS 里有 A1，但 scripts/ 下只有子 ASIN 决策那一个
            # Runner）。写成「请在本地执行」会让人以为自己少做了一步。
            "message": "A1 的 Runner 还没做，Agent 侧目前只有子 ASIN 决策那一条链",
            "current_step": 0, "total_steps": len(st)}}

    st = [
        step("读取广告对象事实", "正常", "覆盖 %d 个广告对象" % len(by),
             ["广告对象名称与类型", "投放对象内容", "运营已有记录"]),
        step("判断广告目的标签", "正常", "产出 %d 条建议" % len(items),
             ["命名线索", "投放内容"]),
        step("标注确认状态", "正常",
             "待运营确认 %d 条，无法识别 %d 条" % (len(items) - unrec, unrec),
             ["确认状态词表"]),
        step("附上判断依据", "正常" if with_reason == len(items) else "缺失",
             "%d/%d 条带依据" % (with_reason, len(items)),
             ["名称线索", "投放对象"]),
        step("按对象落库", "正常", "%d 次运行" % len(by), None),
    ]
    n_ok = len([x for x in st if x["status"] == "正常"])
    return {"steps": st, "run": {
        "status": "完成" if n_ok == len(st) else "未完成",
        "message": "" if with_reason == len(items)
                   else "有 %d 条没带判断依据" % (len(items) - with_reason),
        "created_at": latest_at, "model_version": model,
        "current_step": n_ok, "total_steps": len(st)}}

def task_run(child_asin: str, current_hash: str,
             objects: dict | None = None,
             do_trigger: bool = False) -> dict:
    """外壳任务面板的 run 路由。回执形状照 shell.js 的契约。

    do_trigger=True 时先起一次真实 Runner 再回状态；外壳随后轮 poll 路由。
    """
    if not child_asin:
        return {"steps": [], "run": {"status": "失败",
                                     "message": "先在页面上选一个子 ASIN"}}
    fired = trigger(child_asin) if do_trigger else None
    if fired and not fired["ok"]:
        return {"steps": steps({}), "run": {
            "status": "失败", "object_id": child_asin,
            "message": fired["message"],
            "current_step": 0, "total_steps": len(LOOP)}}

    res = agent_result.latest(child_asin, current_hash, objects=objects)
    ok = res.get("condition") == "正常"
    ran = bool(res.get("run_id"))
    busy = running(child_asin)
    st = steps(res)
    n_ok = len([x for x in st if x["status"] == "正常"])
    tail = runner_tail(child_asin)

    err = runner_failed(child_asin)
    rid, in_flight = reported_run_id(child_asin, res)
    # 刚触发那一刻日志还是空的，running() 判不出来，但它确实在跑。
    # 不特判的话按钮点下去第一帧显示「失败」，看的人以为没起来。
    just_fired = bool(fired and fired["ok"])
    if just_fired and not err:
        return {"steps": steps({}), "run": {
            "run_id": trigger_id(child_asin),
            "object_id": child_asin,
            # 外壳认「加载中」为「同一 id 但还在跑，继续跟踪」
            "status": "加载中",
            "message": "已触发本地 Runner，正在读取干净事实",
            "current_step": 0, "total_steps": len(LOOP)}}
    if in_flight:
        # 落库那条是上一次的结果，这次还在飞。绝不能报「完成」——
        # 那会把上一次的结论当成这次的成果摆出来。
        status = "失败" if err else "加载中"
        # 跑到第几步：读 Runner 自报的步号。
        # 先前拼「B0b + 已提交」这类关键词去数——它每个输出点的措辞都不一样
        # （已提交成功／输出已接受／诊断已提交并接受），拼词必然漏。
        done = runner_progress(child_asin)
        st = steps({})
        for i in range(min(done + 1, len(st))):
            st[i]["status"] = "正常" if i < done else "加载中"
        return {"steps": st, "run": {
            "run_id": rid, "object_id": child_asin, "status": status,
            "message": ("这次没跑完：" + err) if err else
                       ("Runner 正在跑：" + (tail[-1][:110] if tail else "刚起来")),
            "current_step": done + 1, "total_steps": len(st),
            "runner_tail": tail}}
    if ok:
        status = "完成"
    elif busy:
        status = "运行中"
    elif err:
        status = "失败"
    elif ran:
        status = "未完成"
    else:
        status = "失败"

    msg = res.get("message") or ""
    if status == "运行中":
        prog = [x for x in tail if x.startswith("[") or "调用成功" in x]
        msg = "Runner 正在跑：" + (prog[-1][:120] if prog else "刚起来")
    elif err and not ok:
        # 只在这次没成功时才提日志里的报错。
        # 少了 not ok 这个条件，成功那次也会翻出上一次的旧报错，
        # 页面就成了「十步全绿但底下写着失败」。
        msg = "上一次这一步没跑完：" + err
    elif not ran:
        msg = ("已触发，等 Runner 产出" if fired and fired["ok"]
               else "尚未运行，点「运行」触发本地 Runner")

    return {
        "steps": st,
        "run": {
            # 用最新一行（含 running 占位），外壳靠它判开跑没有
            "run_id": rid,
            "object_id": child_asin,
            "status": status,
            "message": msg,
            "created_at": res.get("completed_at") or res.get("created_at"),
            "data_as_of": res.get("data_as_of"),
            "model_version": res.get("model_version"),
            "current_step": n_ok,
            "total_steps": len(st),
            "runner_tail": tail,
        },
    }
