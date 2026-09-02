"""接入范例 · 取数层。

演示契约 6.1–6.4 的做法：路径从 core.paths 取、只读打开、缓存能被一次清干净。
真实模块把 SQL 写在这里，判断逻辑写在 compute.py，两层分开。
"""

from __future__ import annotations

from functools import lru_cache

from core import db, paths

# 上屏用的中文词表在读取边界完成映射（契约 6.4 / 6.6）。
# 库里的 direct / derived / constructed 不允许出现在返回给前端的载荷里。
_ORIGIN_TO_NATURE = {
    "direct": "真实",
    "derived": "推导",
    "constructed": "模拟",
    "mixed": "混合",
}

# 上屏字段用**白名单**，不是黑名单。
# 黑名单会漏：数据包加一列就又漏一次，而 dim_product_child 里正好有 provenance /
# attribute_provenance 这种存 JSON 的内部列，漏出去就是一整段乱码上屏。
# 键是库里的列名，值是中文成品文案 —— 页面拿到的是右边这些字，不做二次映射。
FIELD_LABELS = {
    "style_no": "款号",
    "product_name": "品名",
    "style_name": "款式",
    "category": "品类",
    "colorway": "颜色",
    "size": "尺码",
    "combination": "组合内容",
    "owner": "负责人",
    "operator": "运营",
    "operations_group": "运营组",
    "goods_status": "商品状态",
    "category_rank": "类目排名",
    "rating": "评分",
    "product_lifecycle": "生命周期",
    "attribute_quality_status": "属性完整度",
}

# 枚举值在读取边界映射成中文。attribute_quality_status 是库里唯一还留着英文的列
# （complete / partial / missing），342 行里非 complete 的有 31 个 —— 不是恒定值，
# 不能当噪音删掉，映射成中文照常显示。
_ENUMS = {
    "attribute_quality_status": {"complete": "完整", "partial": "部分", "missing": "缺失"},
}

# 属性完整度只在**完全没有**属性时才算对象级的数据缺失。
# 第一版把 partial 也映射成「缺失」，结果顶部挂一个「缺失」徽标、下面又有一行
# 「属性完整度：部分」—— 同一件事说两遍，而且顶部那句把话说重了。
_QUALITY_TO_CONDITION = {"complete": "正常", "partial": "正常", "missing": "缺失"}


def display(col: str, value):
    """把库里的值变成能直接上屏的东西。枚举映射只在这里做，页面不参与。"""
    table = _ENUMS.get(col)
    if table:
        return table.get(str(value).strip().lower(), str(value))
    return value


def nature_of(value_origin: str | None) -> str:
    return _ORIGIN_TO_NATURE.get((value_origin or "").strip().lower(), "真实")


def condition_of(quality: str | None) -> str:
    return _QUALITY_TO_CONDITION.get((quality or "").strip().lower(), "正常")


def _con():
    """按线程取只读连接。

    **不要用 @lru_cache 缓存单个连接** —— 服务是多线程的，前端会并行发请求，
    一个连接被两个线程同时 execute 会偶发 `database disk image is malformed`
    （文件没坏，是连接不能并发用）。db.pool() 按线程各给一个。
    """
    return db.pool(paths.PRODUCT_DB)


@lru_cache(maxsize=1)
def spine() -> list[dict]:
    """产品对象脊椎。只取身份字段，不碰任何日粒度大表——489MB 的包不能整读。"""
    return db.rows(
        _con(),
        """
        select c.child_asin, c.parent_asin, c.product_name, c.style_name,
               c.colorway, c.size, c.product_lifecycle
        from dim_product_child c
        order by c.parent_asin, c.child_asin
        """,
    )


@lru_cache(maxsize=1)
def parents() -> list[dict]:
    return db.rows(
        _con(),
        "select parent_asin, coalesce(product_name, parent_asin) as label from dim_product_parent order by parent_asin",
    )


def child(child_asin: str) -> dict | None:
    return db.one(
        _con(),
        """
        select c.*, p.product_name as parent_name
        from dim_product_child c
        left join dim_product_parent p on p.parent_asin = c.parent_asin
        where c.child_asin = ?
        """,
        (child_asin,),
    )


def clear_caches() -> None:
    """外壳热重载时调用（契约 8.7）。散落的 lru_cache 必须能从这里一次清干净。

    连接不在这里关：它按线程存在 core.db 里，进程内复用是对的。
    """
    for fn in (spine, parents):
        fn.cache_clear()
