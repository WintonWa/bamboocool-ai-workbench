"""反证 context_hash 的口径：该敏感的敏感，该不敏感的不敏感。

按 00-通用方法与规范/09-广告Agent重建两侧分工.md 方案 1：
hash 是「页面上下文新鲜度指纹」，不是「模型输入全文指纹」。

必须敏感（变了要重跑）：规则参数、运营设定的目标、数据包版本、上游 run_id
必须不敏感（否则循环依赖：Agent 的产出决定它自己输入的指纹）：
  预烤约束 / 匹配度 / 竞品压力 / 结构问题 / 预烤任务诊断建议 / AI 建议的目的标签

做法：临时改扩展库里的预烤结论，看 hash 变不变，改完回滚。
"""
import pathlib
import sqlite3
import sys
from pathlib import Path

WB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WB))
EXT = ("/Users/linsen/BAM/04-广告分析模块/"
       "02-数据构建/page2-ext/page2_decision_ext.sqlite")
ASIN = "B0B3LWGP36"


def h(**query):
    from modules.ads import compute, data, rules
    con = data.connect()
    try:
        ctx = compute.build_context(con, ASIN, None, rules.resolve(query))
        return ctx["context_hash"] if ctx else None
    finally:
        con.close()


def invalidate():
    from modules.ads import data
    data.invalidate()


base = h()
print("基线 hash:", base[:16], "\n")

print("=== 必须敏感 ===")
for k, v in (("ads.stale_days", "9"), ("ads.grain", "TARGET"),
             ("ads.daily_basis", "search_term_exact_day_sum")):
    got = h(**{k: v})
    ok = got != base
    print("  %-30s %s  %s" % (k, got[:16], "变了 ✓" if ok else "没变 ✗"))

print("\n=== 必须不敏感（改预烤结论）===")
CASES = [
    ("预烤约束 label", "update ext_goal_constraint set label='压力测试改过'"
     " where goal_version=(select goal_version from ext_product_goal"
     " where child_asin='%s')" % ASIN),
    ("匹配度档位", "update ext_keyword_match set match_level='low'"
     " where kw_id in (select kw_id from ext_keyword_position"
     " where child_asin='%s')" % ASIN),
    ("竞品压力分类", "update ext_competitor_pressure set pressure_type='price'"
     " where child_asin='%s'" % ASIN),
    ("结构问题说明", "update ext_structure_issue set detail='压力测试改过'"
     " where decision_id='dec_%s_20260803'" % ASIN),
    ("预烤诊断结论", "update ext_diagnosis set what_happened='压力测试改过'"
     " where decision_id='dec_%s_20260803'" % ASIN),
    ("预烤建议方向", "update ext_recommendation set direction='PAUSE'"
     " where decision_id='dec_%s_20260803'" % ASIN),
]
# 整库复制一份当备份，跑完原样还回去——不在真库上留任何痕迹
import shutil
BAK = EXT + ".hashscope.bak"
shutil.copy2(EXT, BAK)
bad = []
try:
    for name, sql in CASES:
        cx = sqlite3.connect(EXT)
        try:
            n = cx.execute(sql).rowcount
            cx.commit()
        except Exception as e:                                # noqa: BLE001
            cx.close()
            print("  %-16s 跳过（%s）" % (name, str(e)[:34]))
            continue
        cx.close()
        invalidate()
        got = h()
        ok = got == base
        print("  %-16s 改了 %d 行 → %s  %s"
              % (name, n, got[:16], "没变 ✓" if ok else "变了 ✗ 循环依赖"))
        if not ok:
            bad.append(name)
        shutil.copy2(BAK, EXT)      # 每条验完立刻还原，互不干扰
        invalidate()
finally:
    shutil.copy2(BAK, EXT)
    pathlib.Path(BAK).unlink(missing_ok=True)
    invalidate()
    print("\n扩展库已还原，未留痕迹。")
print("循环依赖项:", bad or "无")
sys.exit(1 if bad else 0)
