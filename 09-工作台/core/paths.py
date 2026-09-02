"""集中声明全部外部路径、端口与全局口径。

契约 6.1：路径集中在这里并支持环境变量覆盖，业务文件里不写死绝对路径。
两个旧 demo 一个把路径写死在 lib/data.py、一个用 os.environ.get 带字面量默认值，
口径不一，这里统一成"字面量默认值 + 环境变量可覆盖"。
"""

from __future__ import annotations

import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent          # 09-工作台/
REBUILD_ROOT = APP_ROOT.parent                             # 
WEB_ROOT = APP_ROOT / "web"
MODULES_DIR = APP_ROOT / "modules"


def _path(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw).expanduser().resolve() if raw else default


def _flag(env: str, default: bool) -> bool:
    raw = os.environ.get(env)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


# ---- 服务 ----------------------------------------------------------------
HOST = "127.0.0.1"                                         # 只绑回环，不对外
PORT = int(os.environ.get("WORKBENCH_PORT", "18820"))

# 开发模式：模块 .py 改动后按 mtime 热重载（契约 8.7）
DEV = _flag("WORKBENCH_DEV", True)

# 只加载指定模块，逗号分隔；空 = 全部（契约 8.6）
ENABLED_MODULES = tuple(
    x.strip() for x in os.environ.get("WORKBENCH_MODULES", "").split(",") if x.strip()
)

# ---- 全局口径 ------------------------------------------------------------
# 统一基准日。整站数字都是这一天的口径，顶栏显示它而不是今天。
AS_OF = os.environ.get("WORKBENCH_AS_OF", "2026-08-03")

# ---- 数据包 --------------------------------------------------------------
# 产品对象脊椎：342 子 ASIN / 5 父 ASIN，dim_product_child / dim_product_parent
PRODUCT_DB = _path(
    "WORKBENCH_PRODUCT_DB",
    REBUILD_ROOT
    / "02-产品销售库存模块/02-数据构建/v0.3.0/bamboocool_product_sales_inventory_v0.3.0.sqlite",
)
ADS_DB = _path(
    "WORKBENCH_ADS_DB",
    REBUILD_ROOT / "04-广告分析模块/02-数据构建/v0.2.0/advertising_demo.sqlite",
)
KEYWORD_DB = _path(
    "WORKBENCH_KEYWORD_DB",
    REBUILD_ROOT / "07-关键词分析模块/02-数据构建/v0.1.0/keyword_demo.sqlite",
)
COMPETITOR_DB = _path(
    "WORKBENCH_COMPETITOR_DB",
    REBUILD_ROOT / "08-竞品分析模块/02-数据构建/v0.1.0/competitor_demo.sqlite",
)

# ---- AI Agent -----------------------------------------------------------
# 独立的 Pi Agent 服务。外壳反代 /api/agent/* 过去，浏览器只见一个 origin。
AGENT_ORIGIN = os.environ.get("WORKBENCH_AGENT_ORIGIN", "http://127.0.0.1:18812")
