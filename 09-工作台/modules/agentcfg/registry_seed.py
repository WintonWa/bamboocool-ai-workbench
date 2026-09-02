"""Agent 登记表。

**这里是过渡落点，不是最终归属。**

每个 Agent 最终应该由**它所属的模块**在自己的 `MODULE["agents"]` 里声明 ——
和 params、tasks 一样，谁的东西谁声明，外壳不持有清单。
但现在四个业务模块一个都还没声明，而客户需要看到「Agent 的分析方式和门槛
边界可以自定义」这件事，所以先在这里登记，页面上标成「待模块认领」。

认领的做法：把下面某一项整块搬到该模块的 `module.py` 的 `MODULE["agents"]` 里，
再从这里删掉。门禁 G25 会统计还有几项没认领 —— 那个数应该只减不增。

内容来源，一条都不是编的：
  需求预测   01-方案与数据需求/07-预测Agent接口契约.md v0.3 §0 职责划分
  盘点结论   01-方案与数据需求/10-盘点结论Agent接口契约.md v0.2 §0 §1
  其余三个   分析方式**尚未拍定**，所以 judges 留空并在 note 里说明缺什么。
             这不是偷懒：把没定的判断写成看起来定了的样子，比留空更坏 ——
             下游会照着它实现，等真契约出来时已经错了一轮。
"""

from __future__ import annotations

# 触发方式词表，与 07 契约 fact_forecast_run.trigger 一致
TRIGGERS = {"weekly": "每周定时", "manual": "运营手动", "priority": "重点对象天跑"}

SEED = [
    {
        "id": "demand-forecast",
        "label": "需求预测",
        "desc": "判断真实需求，产出未来 90 天逐日预测与区间；库存够不够由工作台算",
        "owner": "inventory",
        "status": "未接通",
        "model_version": None,
        "trigger": ["weekly", "manual", "priority"],
        # Agent 不可替代的判断 —— 这三条是普通代码做不了的
        "judges": [
            "历史销量有没有被缺货扭曲（低销量是没需求，还是那几天没货可卖）",
            "站内活动对需求的影响有多大，活动结束后回落到什么水平",
            "这个对象的生命周期在哪一段（爬坡、平稳、衰退）",
        ],
        # 确定性算术，留在工作台。放进来的理由见 07 契约 §0：
        # 算术留在工作台，阈值才能在参数面板上改并立刻重算。
        "computed": [
            "逐日库存余额", "覆盖天数", "安全线突破日", "预计断货日",
            "缺口量", "超量件数", "最晚补货日", "建议补货量",
            "承接能力", "五类风险",
        ],
        "needs": ["历史逐日销量（730 天）", "事件日历", "库存快照与在途批次"],
        "outputs": [
            "未来 90 天逐日需求预测",
            "预测区间（悲观 / 基准 / 乐观三条线）",
            "每个调整项的影响幅度与中文依据",
            "本次判断的确定程度与理由",
        ],
        "thresholds": [
            "inv.safety_days_override",
            "inv.target_cover_days",
            "inv.max_cover_days",
            "inv.low_velocity_daily_units",
            "inv.internal_release_lag_days",
        ],
        "contract": "01-方案与数据需求/07-预测Agent接口契约.md",
        "note": "契约已定到 v0.3，四张表的形状是确定的。链子断在写库那一步："
                "Pi 循环目前全库只读、产出只是一段文本，没有数字落表。",
    },
    {
        "id": "stock-verdict",
        "label": "盘点结论",
        "desc": "把一个对象当下该不该动说成五条结论，排在页面最前",
        "owner": "inventory",
        "status": "已接通",
        "model_version": "deepseek/deepseek-v4-flash",
        "trigger": ["weekly", "manual"],
        "judges": [
            "这个对象当下到底该不该动、动什么",
            "两个口径同时为真时该怎么说（覆盖 49.4 天与 08-08 断货并存，"
            "因为那批 609 件 08-28 才到，比断货晚 20 天）",
            "五条结论里哪一条是当下最要紧的，排在最前",
        ],
        "computed": ["各口径覆盖天数", "断货日", "到货时间轴", "缺口天数"],
        "needs": ["库存快照与在途 ETA", "需求预测结果", "各口径覆盖与断货日"],
        "outputs": ["结论先行带五条", "每条结论的依据指针", "本次运行时间"],
        "thresholds": [
            "inv.availability_min_rate",
            "inv.aged_share_max",
            "inv.fee_sales_ratio_max",
            "inv.fee_gross_ratio_max",
        ],
        "contract": "01-方案与数据需求/10-盘点结论Agent接口契约.md",
        "note": "2026-08-31 06:57 跑通：真 LLM 落库、页面读表、22 个数字与确定性层逐个对上。"
                "但契约 §8 的 10 条门禁一条都还没实现 —— 其中「混格式时间戳仍取对」"
                "守的是已经复现过的静默错误（代码修了，没有门禁挡回归）。"
                "另外只有 B0B3LM36WB 有结论，缺一个零风险对象作对照。",
    },
    {
        "id": "stock-group-review",
        "label": "库存总体分析",
        "desc": "按分组整合每个对象的子 Agent 结论，突出重点，落到异常总览与库存全览",
        "owner": "inventory",
        "status": "待声明",
        "model_version": None,
        # 它只能跟在两个子 Agent 之后跑。现有触发词表（每周定时 / 运营手动 /
        # 重点对象天跑）里没有「跟在别人后面」这一项，不自造词，留空。
        "trigger": [],
        "judges": [
            "这个分组里哪几个对象是重点 —— 从子 Agent 已有的逐个结论里挑，不重算一遍",
            "这个分组整体处在什么状态，一句话说清",
        ],
        # 分组的计数、合计与分布是算术，留在工作台 —— 门槛在参数面板一改就要立刻重算，
        # 这是「算术留在工作台」那条规矩的原因（见职责表）。
        "computed": [
            "分组内的对象数",
            "各风险类型的对象计数与占比",
            "影响件数合计",
            "严重度分布",
            "承接能力分布",
        ],
        "needs": [
            "盘点结论 Agent 的逐个对象结论",
            "需求预测 Agent 的逐个对象预测与判断",
            "分组口径：按负责人 / 款号 / 组合 / 生命周期 / 店铺 / 父 ASIN 筛，或全盘 342 个"
            "（都是库存模块 filter_options 里已有的真实维度，不新增筛选字段）",
        ],
        "outputs": [
            "这个分组的总体结论",
            "重点对象清单与每个对象的入选理由",
            "上屏位置：异常总览（inv-risk）与库存全览（inv-scope）两个板块",
        ],
        # 它突出的「重点」是这些门槛定义出来的风险 —— 改任何一个，它眼里的重点就会变，
        # 所以这几个键要显式声明。两组都列：风险阈值决定什么算风险，
        # 库存承接决定缺口与超量。
        "thresholds": [
            "inv.availability_min_rate",
            "inv.aged_share_max",
            "inv.fee_sales_ratio_max",
            "inv.fee_gross_ratio_max",
            "inv.safety_days_override",
            "inv.target_cover_days",
            "inv.max_cover_days",
        ],
        "contract": None,
        "note": "王楠 2026-08-31 提出，还没做，后面会做。"
                "已定的：分组按库存现有筛选维度（含按负责人，现在有 3 个人）或全盘；"
                "原理是先拿每个子 Agent 的逐个结论、再整合、再突出重点；"
                "产出落到异常总览与库存全览。"
                "没定的：契约文档还没有，落表形状没定；"
                "「突出重点」按什么排序、取前几个没定；"
                "两个子 Agent 对同一对象结论不一致时以哪个为准没定 —— "
                "这一条最要紧，因为盘点结论说「该补货」而需求预测说「需求在衰退」是会同时出现的。",
    },
    {
        "id": "keyword-opportunity",
        "label": "关键词机会与风险",
        "desc": "从词级位置变化里挑出值得动的词，并给优先级",
        "owner": "keyword",
        "status": "待声明",
        "model_version": None,
        "trigger": ["weekly"],
        "judges": [],
        "computed": [
            "词的需求规模", "自然位与广告位变化", "连续下滑天数",
            "词组按权分摊后的汇总", "四项加权后的优先级分数",
        ],
        "needs": ["词级历史位置序列", "搜索量口径", "自有核心词清单"],
        "outputs": [],
        "thresholds": [
            "kw.weak_rank", "kw.streak_days", "kw.rank_shift",
            "kw.w_demand", "kw.w_change", "kw.w_push", "kw.w_evidence",
        ],
        "contract": None,
        "note": "分析方式未拍定。缺的是：优先级四项权重该由 Agent 按对象调，"
                "还是全局固定由运营在这里改？两种做法对客户的含义完全不同。",
    },
    {
        "id": "keyword-child-goal",
        "label": "子体关键词布局",
        "desc": "给定这个子体当前的推广目标，判断它的词该怎么排布、缺哪些词、该推哪个",
        "owner": "keyword",
        "status": "待声明",
        "model_version": None,
        "trigger": [],
        "judges": [
            "按这个子体当前的目标，它现在的词覆盖够不够、缺的是哪一类词",
            "该把力气放在哪几个词上 —— 守住已有位置，还是去抢没覆盖到的",
            "目标改过之后，原来的词布局还成不成立",
        ],
        "computed": [
            "该子体的词覆盖数与位置分布",
            "词级的展现、点击与转化",
            "目标的当前版本与历史版本",
        ],
        "needs": [
            "该子体当前的推广目标与历史版本（dim_keyword_child_goal）",
            "词 × 子体的位置与表现",
            "关键词机会与风险 Agent 已给出的词级优先级",
        ],
        "outputs": [
            "这个子体的词布局结论",
            "该推 / 该守 / 该放弃的词，各自的理由",
            "目标与现有布局不一致的地方",
        ],
        # 只声明直接相关的两个：什么算位置弱、推广角色权重。
        # 另外三个 w_* 是「关键词机会与风险」那个 Agent 的打分权重，
        # 这个 Agent 读它的产出，不重新打分 —— 同一个门槛不挂两个负责人。
        "thresholds": [
            "kw.weak_rank",
            "kw.w_push",
        ],
        "contract": None,
        "note": "2026-08-31 补登，还没做。"
                "为什么单列一个：关键词模块自己声明的判断对象是三层 —— "
                "「市场关键词 / 关键词 × 子ASIN / 关键词 × 子ASIN × 当前目标」，"
                "而「关键词机会与风险」那条只覆盖了词级涨跌与优先级，第三层没有负责人。"
                "第三层确实存在：库里有 dim_keyword_child_goal（当前目标 + 推广角色 + 目标历史版本），"
                "页面三「子 ASIN 关键词盘点」就是它的上屏位置，目前覆盖 30 个重点子体。"
                "没定的：它和「关键词机会与风险」是两个 Agent 还是一个 Agent 的两步；"
                "目标是人填的还是要判的（现在库里是给定的）。",
    },
    {
        "id": "competitor-threat",
        "label": "竞品威胁判定",
        "desc": "盯竞品降价、排名与关键词位置，判断哪些构成真威胁",
        "owner": "competitor",
        "status": "待声明",
        "model_version": None,
        "trigger": ["weekly"],
        "judges": [],
        "computed": [
            "降价幅度与持续天数", "价差变动", "排名变动",
            "关键词位置变动", "产品族代表比例",
        ],
        "needs": ["竞品价格与排名历史", "自有对应对象的同期数据", "产品族归属"],
        "outputs": [],
        "thresholds": [
            "cmp.price_drop_pct", "cmp.gap_shift_pct", "cmp.rank_shift_pct",
            "cmp.kw_rank_shift", "cmp.min_duration_days",
            "cmp.family_coverage_pct", "cmp.stale_days",
        ],
        "contract": None,
        "note": "分析方式未拍定。缺的是：什么算「威胁」要不要 Agent 判断，"
                "还是纯阈值命中即可 —— 如果是纯阈值，这个就不该叫 Agent。",
    },
    {
        "id": "ads-anomaly",
        "label": "广告异常与决策",
        "desc": "四类异常里判断哪些该调价、哪些该扩量、哪些只是样本不够",
        "owner": "ads",
        "status": "待声明",
        "model_version": None,
        "trigger": ["weekly", "manual"],
        "judges": [],
        "computed": [
            "绝对阈值命中", "相对自身历史的环比变化",
            "相对同组中位的偏离", "样本量是否够判",
        ],
        "needs": ["广告对象逐日表现", "同组对象分布", "库存覆盖天数"],
        "outputs": [],
        "thresholds": [
            "ads.acos_max", "ads.acos_rise", "ads.cvr_drop", "ads.cpc_max",
            "ads.min_clicks", "ads.min_clicks_per_half", "ads.stale_days",
            "ads.coverage_warn_days", "ads.invalid_click_rate_max",
            "ads.budget_capped_at", "ads.acos_peer_dev_max",
        ],
        "contract": None,
        "note": "分析方式未拍定。四类异常判定目前是纯算子。缺的是："
                "「该不该调价 / 该不该扩量」这一步交给 Agent，还是继续算子出规则、人来定。",
    },
    {
        "id": "ads-purpose-label",
        "label": "广告目的标签",
        "desc": "从广告对象的命名、结构与投放行为里判断它到底在干什么，补上认不出来的那些",
        "owner": "ads",
        "status": "未接通",
        "model_version": None,
        "trigger": ["manual"],
        "judges": [
            "这个广告对象在干什么 —— 抢大词、捡漏、拦竞品、再营销，还是别的",
            "证据够不够下这个判断；不够就如实说认不出来，不硬给一个标签",
        ],
        "computed": [
            "每个广告对象的展示 / 点击 / 花费 / 订单",
            "已有标签的覆盖数与无法识别数",
        ],
        "needs": [
            "广告对象的命名与层级结构（Campaign / 广告组 / 投放对象）",
            "该对象的投放行为（匹配类型、投放对象构成、日粒度序列）",
            "产品侧身份（广告 ASIN 映射，缺映射时要说清）",
        ],
        "outputs": [
            "每个广告对象的目的标签建议",
            "下这个判断的依据",
            "认不出来的对象与认不出来的原因",
        ],
        # 只声明「够不够判」这一类门槛。效率类（acos / cvr / cpc）约束的是
        # 表现好不好，不约束「它在干什么」—— 混进来会让门槛看起来管了它不管的事。
        "thresholds": [
            "ads.min_clicks",
            "ads.stale_days",
            "ads.coverage_warn_days",
        ],
        "contract": None,
        "note": "代码里已经有了，但一直没登记进这张表 —— 2026-08-31 补登。"
                "已有的：可运行任务 ads-purpose-label（run=loop-a1）、读取函数 "
                "latest_purpose_labels()、落表形状（fact_ads_agent_run.run_type='purpose_label' "
                "+ fact_ads_agent_output.output_point='A1'）。"
                "为什么标未接通：库里 run_type 只有 child_decision 与空值两种，"
                "purpose_label 一次都没成功跑过，读取函数永远返回「尚未完成 A1 运行」。"
                "所以页面上现在那 54 个对象的目的标签是数据包里烤好的，不是 Agent 判的 —— "
                "其中 11 个是「无法识别」，正是这个 Agent 该补的位置。",
    },
    {
        "id": "overview-digest",
        "label": "运营总览",
        "desc": "读完库存 / 关键词 / 竞品 / 广告四个模块的结论，写一份总览结论",
        "owner": "overview",
        "status": "待声明",
        "model_version": None,
        # 触发方式留空不是漏写：它只能跟在四个模块之后跑，而现有触发词表
        # （每周定时 / 运营手动 / 重点对象天跑）里没有「跟在别人后面」这一项。
        # 自造一个词会让它看起来像已经定了，所以留空，缺什么写在 note 里。
        "trigger": [],
        "judges": [],
        "computed": [],
        # 需要什么上下文是确定的 —— 它的职责就是读这四份结论。
        # 但四份里现在只有一份真的落了表，前端那句「缺一项就不该开跑」正好是当下的真状态。
        "needs": [
            "库存模块的盘点结论与需求预测结果",
            "关键词模块的机会与风险结论",
            "竞品模块的威胁判定",
            "广告模块的异常与决策结论",
        ],
        "outputs": [],
        # thresholds 故意为空。它的判断方式还没拍定，此时写任何一个门槛键，
        # 等于替客户拍了一个没人拍过的决定；而上游四个模块的门槛各自归属各自的
        # Agent，挪到这里会让同一个门槛出现两个负责人。门禁 G25 只查键存不存在，
        # 凑几个真键能过门禁 —— 但那正是这条注释要拦住的事。
        "thresholds": [],
        "contract": None,
        "note": "没有实现，一行代码都还没有；总览模块本身也还是占位页。"
                "四份上游结论里现在只有库存的盘点结论真的落了表，"
                "关键词 / 竞品 / 广告三个 Agent 的分析方式本身都还没拍定 —— "
                "也就是「读完四个模块的结论」这句话眼下只有四分之一有东西可读。"
                "缺的是：总览是把四条结论按要紧程度排个序（那是排序算术，不该叫 Agent），"
                "还是要给出跨模块的合并判断（库存说该补货、广告说该减投，两条撞车时听谁的）。"
                "这一步没定之前不写 judges 与 outputs。",
    },
]


# ===========================================================================
# 运行记录的落点：跑过的那些 run 写在哪张表
# ===========================================================================
#
# **这是数据依赖，不是代码依赖。** G12 禁的是 import 兄弟模块的 Python；
# 这里只按路径只读打开兄弟模块自己的 derived 库，一行它们的代码都不引。
# 之所以由本模块读：run 记录要一处按时间汇总，而每张表归属不同模块，
# 谁都不该替别人建一份汇总表 —— 那才是真的碎片化。
# 和上面的登记表一样，这里也是**过渡落点**：某个 Agent 被它的模块认领时，
# 它这一条也该跟着搬到那个模块，由模块自己回自己的运行记录。
#
# 六张表的列名各不相同，所以每条声明把列的**角色**写出来，
# 读表的代码只认角色不认列名（module.py 的 _collect）。
# 声明了但库里没有的列会被跳过并如实报出来，不让一列改名打掉整页。

RUN_SOURCES = [
    {
        "sid": "inv-verdict",                      # 存档键前缀：run_id 跨库会重名
        "agent_id": "stock-verdict",
        "db": "inventory/derived/verdict_agent.sqlite",
        "table": "fact_child_verdict_run",
        "source": "库存 · 盘点结论运行表",
        "subject_col": "child_asin",
        "subject_kind": "子 ASIN",
        "summary_col": None,                       # 五条结论在 item 表里，这张表没有摘要列
        "extra": [
            ("method_version", "方法版本"),
            ("input_forecast_run_id", "输入的预测运行"),
        ],
    },
    {
        "sid": "inv-forecast",
        "agent_id": "demand-forecast",
        "db": "inventory/derived/forecast_agent.sqlite",
        "table": "fact_child_forecast_agent_run",
        "source": "库存 · 需求预测运行表",
        "subject_col": "child_asin",
        "subject_kind": "子 ASIN",
        "summary_col": "judgment_summary",
        "tags": [("confidence", "确定程度")],       # 值本来就是中文（高 / 中 / 低）
        "extra": [
            ("confidence_reason", "确定程度依据"),
            ("horizon_days", "预测天数"),
            ("actual_run_date", "实际运行日"),
            ("prompt_version", "提示词版本"),
            ("method_version", "方法版本"),
            ("prev_run_id", "上一次运行"),
            ("comparison_snapshot_run_id", "对比基准运行"),
        ],
    },
    {
        "sid": "kw",
        "agent_id": "keyword-opportunity",
        "db": "keyword/derived/keyword_agent_state.sqlite",
        "table": "fact_keyword_agent_run",
        "source": "关键词 · Agent 运行台账",
        "subject_col": "scope",
        "subject_kind": "范围",
        "summary_col": None,
        "extra": [
            ("dataset_version", "数据集版本"),
            ("rule_version", "规则版本"),
        ],
    },
    {
        "sid": "cmp",
        "agent_id": "competitor-threat",
        "db": "competitor/derived/competitor_agent_state.sqlite",
        "table": "fact_competitor_analysis_run",
        "source": "竞品 · 分析运行表",
        "subject_col": "family_asin",
        "subject_kind": "产品族",
        "summary_col": "attention_summary",
        "tags": [("attention_level", "关注度"), ("evidence_level", "证据档位")],
        "extra": [
            ("judgment_summary", "判断小结"),
            ("evidence_reason", "证据依据"),
            ("window_from", "观察窗起"),
            ("window_to", "观察窗止"),
        ],
    },
    {
        "sid": "cmp-v2",
        "agent_id": "competitor-threat",
        "db": "competitor/derived/competitor_agent_state_v2.sqlite",
        "table": "fact_competitor_analysis_run",
        "source": "竞品 · 分析运行表 v2",
        "subject_col": "family_asin",
        "subject_kind": "产品族",
        "summary_col": "attention_summary",
        "tags": [("attention_level", "关注度"), ("evidence_level", "证据档位")],
        "extra": [
            ("judgment_summary", "判断小结"),
            ("evidence_reason", "证据依据"),
            ("window_from", "观察窗起"),
            ("window_to", "观察窗止"),
        ],
    },
    {
        "sid": "ads",
        "agent_id": "ads-anomaly",
        "db": "ads/derived/ads_agent_state.sqlite",
        "table": "fact_ads_agent_run",
        "source": "广告 · Agent 运行台账",
        "subject_col": "child_asin",
        "subject_kind": "子 ASIN",
        "summary_col": None,
        "tags": [("mode", "判断模式")],             # 值本来就是中文（条件性判断）
        "extra": [
            ("method_version", "方法版本"),
            ("schema_version", "契约版本"),
            ("dataset_version", "数据集版本"),
            ("rule_version", "规则版本"),
            ("run_type", "运行类型"),
        ],
    },
]

# 每张表共同的三个角色列，六张表列名一致，所以不进上面的声明
TIME_COL = "created_at"          # 真实写库时刻。格式不统一，必须解析后再比，见 module.py._stamp
DONE_COL = "completed_at"        # 有就用来算耗时，没有就不显示
STATUS_COL = "status"
ERROR_COLS = ("error", "error_message")

# ---------------------------------------------------------------------------
# 码值 → 中文
# ---------------------------------------------------------------------------
# 词表照各模块已有的口径抄，不新造词：关注度与证据档位与竞品模块 data.py 一致，
# 触发方式就是上面的 TRIGGERS。
# 只映射**真的在库里出现过的**值。落在词表外的非空值一律显示成「待确认」——
# 回落成英文原值是内部叫法上屏，回落成空白会把写入方的契约违规藏起来。
ATTENTION = {"high": "优先处理", "medium": "持续关注", "low": "留观", "none": "无需处理"}
EVIDENCE = {"sufficient": "证据充分", "partial": "证据部分", "insufficient": "证据不足"}
RUN_STATUS = {"completed": "完成", "failed": "失败", "writing": "进行中"}
SCOPES = {"all": "全部关键词"}

VOCAB = {
    "attention_level": ATTENTION,
    "evidence_level": EVIDENCE,
    STATUS_COL: RUN_STATUS,
    "scope": SCOPES,
    "trigger": TRIGGERS,
}
