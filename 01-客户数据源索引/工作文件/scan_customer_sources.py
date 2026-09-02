#!/usr/bin/env python3
"""Read-only inventory scanner for the Bamboocool customer data package.

The script never writes to the source tree. It extracts workbook/table structure,
field metadata, date coverage, formula/merge information, likely keys, supported
business modules, and data-quality warnings into a machine-readable JSON index.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import posixpath
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from lxml import etree, html as lxml_html


SOURCE_ROOT = Path("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803")
OUTPUT_JSON = Path("/Users/linsen/BAM/01-客户数据源索引/客户数据源索引.json")

VALID_EXTENSIONS = {".xlsx", ".xlsm", ".csv", ".tsv", ".html", ".htm"}
EMPTY_MARKERS = {"", "none", "null", "nan", "n/a", "na", "-", "--", "—"}

OOXML_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
OOXML_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
BUILTIN_DATE_FORMAT_IDS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))

HEADER_KEYWORDS = {
    "asin", "sku", "fnsku", "msku", "日期", "时间", "月份", "年份", "周", "产品", "商品",
    "广告", "活动", "广告组", "关键词", "搜索词", "库存", "销量", "销售额", "订单", "价格",
    "利润", "成本", "费用", "站点", "国家", "状态", "仓库", "负责人", "运营", "投放", "预算",
    "campaign", "keyword", "date", "sales", "orders", "impressions", "clicks", "spend",
    "purchases", "units", "inventory", "price", "cost", "currency", "status", "marketplace",
}

TIME_HEADER_RE = re.compile(
    r"(^|[^a-z])(date|datetime|timestamp|day|week|month|year|period|start\s*date|end\s*date)([^a-z]|$)|"
    r"日期|时间戳|周次|月份|年份|周期|期间|开始日期|结束日期|下单时间|创建时间|报告时间",
    re.I,
)

KEY_PATTERNS = [
    r"(^|\b)(asin|parent\s*asin|child\s*asin)(\b|$)", r"sku", r"fnsku", r"msku",
    r"商品编码|产品编码|货号|款号|item\s*id|product\s*id", r"订单号|order\s*id",
    r"广告活动.*(id|编号|名称)|campaign.*(id|name)", r"广告组.*(id|编号|名称)|ad\s*group",
    r"关键词|keyword", r"搜索词|search\s*term", r"站点|marketplace", r"国家|country",
    r"仓库|warehouse", r"负责人|运营", r"日期|date|月份|month|周|week",
]

SENSITIVE_PATTERNS = [
    r"姓名|联系人|负责人|运营人员|员工|邮箱|email|电话|手机|mobile|phone",
    r"地址|address|邮编|身份证|证件|银行卡|账号|account\s*(id|number)|merchant\s*id",
    r"买家|customer|buyer|recipient|收件人|税号|tax\s*id",
]

MODULE_RULES = {
    "产品/销售/库存": [
        r"库存|备货|补货|产品跟进|销售数据|财务月报|利润测算|物流|仓储|出货",
        r"asin|sku|fnsku|msku|销量|销售额|销售收入|订单|可售|在途|库龄|库存|stock|inventory|sales|orders|units|price|利润|毛利|成本",
    ],
    "广告运营": [
        r"广告|推广|sponsored|campaign",
        r"广告活动|广告组|投放|预算|曝光|点击|花费|acos|roas|impressions|clicks|spend|campaign|ad group",
    ],
    "关键词洞察": [
        r"关键词|搜索词|提示词|keyword|search",
        r"关键词|搜索词|自然排名|广告排名|搜索量|keyword|search term|query",
    ],
    "竞品分析": [
        r"竞品|竞争|benchmark|品类基准",
        r"竞品|竞争|品类|市场份额|benchmark|competitor|category",
    ],
    "物流/补货": [
        r"物流|运输|补货|备货|仓储|出货",
        r"运输|物流|补货|备货|仓库|仓储|入库|到货|在途|船期|时效|运费|shipment|warehouse",
    ],
    "财务/利润": [
        r"财务|利润|成本|费用|月报|测算",
        r"收入|利润|毛利|成本|费用|回款|税|汇率|roi|profit|revenue|cost|fee",
    ],
    "运营记录/复盘": [
        r"产品跟进|动作调整|复盘|周报|月报|运营记录",
        r"动作|调整|问题|原因|结论|复盘|负责人|完成时间|计划|策略",
    ],
}

OBJECT_RULES = {
    "产品/SKU/ASIN": r"asin|sku|fnsku|msku|产品|商品|货号|款号",
    "销售业绩": r"销量|销售额|销售收入|订单|units|sales|revenue|orders",
    "库存快照": r"库存|可售|不可售|在途|库龄|stock|inventory|available",
    "补货/物流批次": r"补货|备货|出货|运输|物流|入库|到货|shipment|warehouse",
    "利润/成本": r"利润|毛利|成本|费用|profit|margin|cost|fee",
    "广告活动/广告组": r"广告活动|广告组|campaign|ad group",
    "广告投放/广告位": r"投放|广告位|targeting|placement|预算|budget",
    "关键词/搜索词": r"关键词|搜索词|keyword|search term|query|提示词",
    "竞品/品类": r"竞品|竞争|品类|benchmark|competitor|category",
    "运营动作/复盘": r"动作|调整|复盘|周报|月报|问题|原因|计划|策略",
}


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in EMPTY_MARKERS
    return False


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value).strip()


def clean_header(value: Any) -> str:
    text = re.sub(r"\s+", " ", text_value(value)).strip()
    text = re.sub(r"^Unnamed:\s*\d+$", "", text, flags=re.I)
    return text


def get_column_letter(index: int) -> str:
    """Minimal dependency-free equivalent of openpyxl.utils.get_column_letter."""
    if index < 1:
        raise ValueError("column index must be >= 1")
    result = []
    while index:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def column_index_from_ref(reference: str) -> int | None:
    match = re.match(r"\$?([A-Z]+)", reference.upper())
    if not match:
        return None
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - 64
    return value


def value_type(value: Any) -> str:
    if is_blank(value):
        return "空值"
    if isinstance(value, bool):
        return "布尔"
    if isinstance(value, datetime):
        return "日期时间"
    if isinstance(value, date):
        return "日期"
    if isinstance(value, time):
        return "时间"
    if isinstance(value, int) and not isinstance(value, bool):
        return "整数"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "特殊数值"
        return "小数"
    if isinstance(value, str):
        if value.startswith("="):
            return "公式"
        stripped = value.strip()
        if re.fullmatch(r"[-+]?\d+(\.\d+)?%", stripped):
            return "百分比文本"
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", stripped.replace(",", "")):
            return "数字文本"
        if parse_date_value(stripped) is not None:
            return "日期文本"
        return "文本"
    return type(value).__name__


DATE_PATTERNS = [
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%Y%m%d",
    "%Y-%m", "%Y/%m", "%Y.%m", "%Y年%m月", "%Y%m",
    "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%b %d, %Y", "%d-%b-%y", "%d-%b-%Y",
]


def parse_date_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, (int, float)) and 20000 <= float(value) <= 80000:
        # Excel serial date, 1899-12-30 epoch.
        try:
            from datetime import timedelta
            return datetime(1899, 12, 30) + timedelta(days=float(value))
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 40:
        return None
    text = re.sub(r"\s+", " ", text)
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    match = re.search(r"(20\d{2})[年./-](\d{1,2})(?:[月./-](\d{1,2}))?", text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1))
        except ValueError:
            return None
    return None


def is_time_field_header(field: str) -> bool:
    # Durations and year-over-year metric labels are not calendar dimensions.
    if re.search(r"平均时间|时长|耗时|去年(曝光|点击|支出|销售|订单|成本)", field, re.I):
        return False
    return bool(TIME_HEADER_RE.search(field))


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:200_000]
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "big5"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def header_score(values: list[Any], style: dict[str, Any] | None = None) -> float:
    nonempty = [v for v in values if not is_blank(v)]
    if len(nonempty) < 2:
        return -100.0
    strings = [text_value(v) for v in nonempty if isinstance(v, str)]
    numeric = [v for v in nonempty if isinstance(v, (int, float)) and not isinstance(v, bool)]
    keyword_hits = sum(
        1 for s in strings
        if any(k in s.lower() for k in HEADER_KEYWORDS)
    )
    unique_ratio = len({text_value(v).lower() for v in nonempty}) / len(nonempty)
    short_ratio = sum(1 for s in strings if len(s) <= 60) / max(1, len(strings))
    score = len(nonempty) * 0.25 + len(strings) * 0.9 + keyword_hits * 4.0
    score += unique_ratio * 2.0 + short_ratio
    score -= len(numeric) * 0.8
    if len(nonempty) == 1:
        score -= 12
    if style:
        score += 2.5 * style.get("bold_ratio", 0)
        score += 1.0 * style.get("fill_ratio", 0)
    return score


def detect_header(rows: list[list[Any]], styles: list[dict[str, Any]] | None = None) -> tuple[int | None, list[int], list[str]]:
    candidates: list[tuple[float, int]] = []
    for index, row in enumerate(rows):
        score = header_score(row, styles[index] if styles and index < len(styles) else None)
        if index > 30:
            score -= (index - 30) * 0.05
        candidates.append((score, index))
    if not candidates:
        return None, [], []
    score, index = max(candidates)
    if score < 1:
        return None, [], []

    primary = rows[index]
    # Include a nearby upper grouping row when it contains labels spanning columns.
    header_rows = [index + 1]
    if index > 0:
        prev = rows[index - 1]
        prev_nonempty = sum(not is_blank(v) for v in prev)
        cur_nonempty = sum(not is_blank(v) for v in primary)
        if 1 < prev_nonempty <= cur_nonempty and header_score(prev) >= score * 0.45:
            header_rows.insert(0, index)

    max_cols = max(len(rows[i - 1]) for i in header_rows)
    fields: list[str] = []
    inherited = ""
    for col in range(max_cols):
        parts: list[str] = []
        for row_no in header_rows:
            row = rows[row_no - 1]
            part = clean_header(row[col] if col < len(row) else None)
            if part:
                if row_no != header_rows[-1]:
                    inherited = part
                parts.append(part)
            elif row_no != header_rows[-1] and inherited:
                parts.append(inherited)
        parts = list(dict.fromkeys(parts))
        field = " / ".join(parts)
        if not field:
            field = f"未命名列_{get_column_letter(col + 1)}"
        fields.append(field)

    while fields and fields[-1].startswith("未命名列_"):
        fields.pop()
    return index + 1, header_rows, fields


def infer_metadata(path_text: str, fields: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    combined_fields = " | ".join(fields)
    combined = f"{path_text} | {combined_fields}".lower()
    modules: list[str] = []
    for module, (path_pat, field_pat) in MODULE_RULES.items():
        if re.search(path_pat, path_text, re.I) or re.search(field_pat, combined_fields, re.I):
            modules.append(module)
    objects = [name for name, pattern in OBJECT_RULES.items() if re.search(pattern, combined, re.I)]
    keys = [field for field in fields if any(re.search(pattern, field, re.I) for pattern in KEY_PATTERNS)]
    sensitive = [
        field for field in fields
        if any(re.search(pattern, field, re.I) for pattern in SENSITIVE_PATTERNS)
        and not re.search(r"品牌新买家|品牌新客", field)
    ]
    if re.search(r"产品跟进表-|动作调整表-|周报|月报|复盘", path_text):
        sensitive.append("文件名可能含员工姓名")
    return list(dict.fromkeys(modules)), list(dict.fromkeys(objects)), list(dict.fromkeys(keys)), list(dict.fromkeys(sensitive))


def make_column_profiles(rows: list[list[Any]], header_row: int | None, fields: list[str]) -> list[dict[str, Any]]:
    if header_row is None or not fields:
        return []
    start = header_row
    profiles: list[dict[str, Any]] = []
    for col_index, field in enumerate(fields):
        values = []
        for row in rows[start:]:
            if col_index < len(row) and not is_blank(row[col_index]):
                values.append(row[col_index])
        sampled = values[:500]
        type_counts = Counter(value_type(v) for v in sampled)
        profile: dict[str, Any] = {
            "field": field,
            "column": get_column_letter(col_index + 1),
            "sample_nonempty_count": len(sampled),
            "sample_types": dict(type_counts.most_common()),
            "dominant_sample_type": type_counts.most_common(1)[0][0] if type_counts else "空值",
        }
        if values:
            normalized = [text_value(v) for v in sampled]
            profile["sample_distinct_count"] = len(set(normalized))
            profile["sample_unique_ratio"] = round(len(set(normalized)) / len(normalized), 4)
        profiles.append(profile)
    return profiles


def find_time_ranges(rows: list[list[Any]], header_row: int | None, fields: list[str]) -> list[dict[str, Any]]:
    if header_row is None:
        return []
    results = []
    for col_index, field in enumerate(fields):
        if not is_time_field_header(field):
            continue
        parsed: list[datetime] = []
        nonempty = 0
        for row in rows[header_row:]:
            if col_index >= len(row) or is_blank(row[col_index]):
                continue
            nonempty += 1
            parsed_value = parse_date_value(row[col_index])
            if parsed_value and datetime(1990, 1, 1) <= parsed_value <= datetime(2100, 12, 31):
                parsed.append(parsed_value)
        item: dict[str, Any] = {
            "field": field,
            "column": get_column_letter(col_index + 1),
            "nonempty_count": nonempty,
            "parsed_count": len(parsed),
        }
        if parsed:
            item["min"] = min(parsed).date().isoformat()
            item["max"] = max(parsed).date().isoformat()
            item["parse_ratio"] = round(len(parsed) / max(1, nonempty), 4)
        results.append(item)
    return results


def quality_issues(
    rows: list[list[Any]], header_row: int | None, fields: list[str],
    effective_rows: int, effective_cols: int, formula_count: int,
    merge_count: int, time_ranges: list[dict[str, Any]], hidden: bool,
) -> list[str]:
    issues: list[str] = []
    if effective_rows == 0 or effective_cols == 0:
        return ["空表"]
    if header_row is None:
        issues.append("未可靠识别表头")
    elif header_row > 10:
        issues.append(f"表头较深（第 {header_row} 行），导入前需跳过说明/标题区")
    elif effective_rows <= header_row:
        issues.append("仅含表头，无明细数据")
    if fields:
        unnamed = sum(f.startswith("未命名列_") for f in fields)
        if unnamed:
            issues.append(f"存在 {unnamed} 个未命名字段")
        duplicates = [name for name, count in Counter(fields).items() if count > 1]
        if duplicates:
            issues.append(f"存在重复字段名：{', '.join(duplicates[:6])}")
    if merge_count:
        issues.append(f"含 {merge_count} 个合并单元格，自动导入需展开/补齐层级表头")
    if formula_count:
        issues.append(f"含 {formula_count} 个公式单元格，读取时需区分公式与缓存结果")
    for item in time_ranges:
        if not item["nonempty_count"] and header_row is not None and effective_rows > header_row:
            issues.append(f"时间字段“{item['field']}”整列为空")
        elif item["nonempty_count"] and not item.get("parsed_count"):
            issues.append(f"时间字段“{item['field']}”未解析出标准日期")
        elif item.get("parsed_count") and item.get("parse_ratio", 1) < 0.6:
            issues.append(f"时间字段“{item['field']}”格式混杂（可解析比例 {item['parse_ratio']:.0%}）")
    if effective_cols > 100:
        issues.append(f"超宽表（{effective_cols} 列），建议按主题拆分")
    if effective_rows > 100_000:
        issues.append(f"大表（{effective_rows} 行），Demo 导入需抽样或预聚合")
    if hidden:
        issues.append("工作表处于隐藏状态")
    return issues


def _local_children(element, name: str):
    return element.xpath(f"./*[local-name()='{name}']")


def _first_local_text(element, name: str) -> str | None:
    matches = _local_children(element, name)
    if not matches:
        return None
    return matches[0].text


def read_shared_strings(package: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in package.namelist():
        return []
    strings: list[str] = []
    with package.open("xl/sharedStrings.xml") as stream:
        for _, element in etree.iterparse(stream, events=("end",)):
            if etree.QName(element).localname != "si":
                continue
            text_parts = element.xpath(".//*[local-name()='t']/text()")
            strings.append("".join(text_parts))
            element.clear()
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]
    return strings


def _looks_like_date_format(format_code: str) -> bool:
    # Strip quoted literals, escaped characters, colours and conditions before
    # testing for Excel date/time tokens. Avoid treating [Red] or plain text as dates.
    code = re.sub(r'"[^"]*"', "", format_code)
    code = re.sub(r"\\.", "", code)
    code = re.sub(r"\[(?!h+\]|m+\]|s+\])[^\]]*\]", "", code, flags=re.I)
    return bool(re.search(r"(^|[^a-z])[ymdhis]+([^a-z]|$)", code, re.I))


def read_date_style_indexes(package: ZipFile) -> set[int]:
    if "xl/styles.xml" not in package.namelist():
        return set()
    with package.open("xl/styles.xml") as stream:
        root = etree.parse(stream).getroot()
    custom_formats: dict[int, str] = {}
    for node in root.xpath(".//*[local-name()='numFmts']/*[local-name()='numFmt']"):
        try:
            custom_formats[int(node.get("numFmtId"))] = node.get("formatCode", "")
        except (TypeError, ValueError):
            continue
    date_styles: set[int] = set()
    cell_xfs = root.xpath(".//*[local-name()='cellXfs']/*[local-name()='xf']")
    for style_index, node in enumerate(cell_xfs):
        try:
            number_format_id = int(node.get("numFmtId", "0"))
        except ValueError:
            number_format_id = 0
        if number_format_id in BUILTIN_DATE_FORMAT_IDS or _looks_like_date_format(custom_formats.get(number_format_id, "")):
            date_styles.add(style_index)
    return date_styles


def read_workbook_metadata(package: ZipFile) -> tuple[list[dict[str, str]], bool]:
    with package.open("xl/workbook.xml") as stream:
        workbook_root = etree.parse(stream).getroot()
    date_1904 = False
    workbook_props = workbook_root.xpath(".//*[local-name()='workbookPr']")
    if workbook_props:
        date_1904 = workbook_props[0].get("date1904", "0").lower() in {"1", "true"}

    relationships: dict[str, str] = {}
    relationship_path = "xl/_rels/workbook.xml.rels"
    if relationship_path in package.namelist():
        with package.open(relationship_path) as stream:
            relationship_root = etree.parse(stream).getroot()
        for relationship in relationship_root.xpath(".//*[local-name()='Relationship']"):
            rel_id = relationship.get("Id")
            target = relationship.get("Target")
            if rel_id and target:
                if target.startswith("/"):
                    resolved = target.lstrip("/")
                else:
                    resolved = posixpath.normpath(posixpath.join("xl", target))
                relationships[rel_id] = resolved

    sheets: list[dict[str, str]] = []
    for sheet in workbook_root.xpath(".//*[local-name()='sheets']/*[local-name()='sheet']"):
        rel_id = sheet.get(f"{{{OOXML_REL_NS}}}id")
        if rel_id is None:
            # Strict OOXML uses a different relationship namespace; local-name fallback.
            for key, value in sheet.attrib.items():
                if etree.QName(key).localname == "id":
                    rel_id = value
                    break
        target = relationships.get(rel_id or "", "")
        sheets.append({
            "name": sheet.get("name", "未命名工作表"),
            "state": sheet.get("state", "visible"),
            "path": target,
        })
    return sheets, date_1904


def _excel_serial_to_datetime(value: float, date_1904: bool) -> datetime:
    epoch = datetime(1904, 1, 1) if date_1904 else datetime(1899, 12, 30)
    return epoch + timedelta(days=value)


def decode_ooxml_cell(
    cell, shared_strings: list[str], date_style_indexes: set[int], date_1904: bool,
) -> tuple[Any, bool, bool]:
    """Return (value, is_formula, is_error) without materializing empty styled cells."""
    formula_text = _first_local_text(cell, "f")
    if formula_text is not None:
        return f"={formula_text}", True, False

    cell_type = cell.get("t", "n")
    value_text = _first_local_text(cell, "v")
    if cell_type == "inlineStr":
        parts = cell.xpath("./*[local-name()='is']//*[local-name()='t']/text()")
        value = "".join(parts)
        return value, False, False
    if value_text is None:
        # A cell with only a style is not data and must not affect effective rows.
        return None, False, False
    if cell_type == "s":
        try:
            index = int(value_text)
            return shared_strings[index] if 0 <= index < len(shared_strings) else value_text, False, False
        except (TypeError, ValueError):
            return value_text, False, False
    if cell_type == "b":
        return value_text == "1", False, False
    if cell_type == "e":
        return value_text, False, True
    if cell_type == "d":
        try:
            return datetime.fromisoformat(value_text.replace("Z", "+00:00")), False, False
        except ValueError:
            return value_text, False, False
    if cell_type in {"str", "inlineStr"}:
        return value_text, False, False

    try:
        number = float(value_text)
        numeric_value: int | float = int(number) if number.is_integer() else number
        try:
            style_index = int(cell.get("s", "0"))
        except ValueError:
            style_index = 0
        if style_index in date_style_indexes:
            try:
                return _excel_serial_to_datetime(number, date_1904), False, False
            except (OverflowError, ValueError):
                pass
        return numeric_value, False, False
    except (TypeError, ValueError):
        return value_text, False, False


def iter_ooxml_cells(
    package: ZipFile, sheet_path: str, shared_strings: list[str],
    date_style_indexes: set[int], date_1904: bool,
):
    """Stream only actual cell elements; callers decide which decoded values to retain."""
    with package.open(sheet_path) as stream:
        for _, element in etree.iterparse(stream, events=("end",)):
            local_name = etree.QName(element).localname
            if local_name != "c":
                if local_name == "row":
                    element.clear()
                    parent = element.getparent()
                    if parent is not None:
                        while element.getprevious() is not None:
                            del parent[0]
                continue
            reference = element.get("r", "")
            row_match = re.search(r"(\d+)$", reference)
            column_index = column_index_from_ref(reference)
            if row_match and column_index:
                value, is_formula, is_error = decode_ooxml_cell(
                    element, shared_strings, date_style_indexes, date_1904,
                )
                if not is_blank(value):
                    yield int(row_match.group(1)), column_index, value, is_formula, is_error
            element.clear()
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]


def scan_worksheet_first_pass(
    package: ZipFile, sheet_path: str, shared_strings: list[str],
    date_style_indexes: set[int], date_1904: bool,
) -> tuple[list[list[Any]], dict[str, int], list[str]]:
    preview_sparse: dict[int, dict[int, Any]] = defaultdict(dict)
    max_row = max_col = nonempty = formulas = errors = 0
    for row_index, column_index, value, is_formula, is_error in iter_ooxml_cells(
        package, sheet_path, shared_strings, date_style_indexes, date_1904,
    ):
        max_row = max(max_row, row_index)
        max_col = max(max_col, column_index)
        nonempty += 1
        formulas += int(is_formula)
        errors += int(is_error)
        if row_index <= 80:
            preview_sparse[row_index][column_index] = value

    preview_rows: list[list[Any]] = []
    preview_last_row = min(80, max_row)
    for row_index in range(1, preview_last_row + 1):
        values_by_col = preview_sparse.get(row_index, {})
        last_col = max(values_by_col, default=0)
        preview_rows.append([values_by_col.get(col) for col in range(1, last_col + 1)])

    merge_ranges: list[str] = []
    with package.open(sheet_path) as stream:
        for _, element in etree.iterparse(stream, events=("end",)):
            if etree.QName(element).localname == "mergeCell":
                reference = element.get("ref")
                if reference:
                    merge_ranges.append(reference)
            element.clear()
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]

    return preview_rows, {
        "effective_rows": max_row,
        "effective_cols": max_col,
        "nonempty_cells": nonempty,
        "formula_cells": formulas,
        "error_cells": errors,
    }, merge_ranges


def scan_worksheet_columns(
    package: ZipFile, sheet_path: str, shared_strings: list[str],
    date_style_indexes: set[int], date_1904: bool,
    header_row: int | None, fields: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if header_row is None or not fields:
        return [], []
    sample_types = [Counter() for _ in fields]
    sample_distinct = [set() for _ in fields]
    sample_counts = [0 for _ in fields]
    time_indexes = {index for index, field in enumerate(fields) if is_time_field_header(field)}
    time_stats = {
        index: {"nonempty": 0, "parsed": 0, "min": None, "max": None}
        for index in time_indexes
    }

    for row_index, column_index, value, _, _ in iter_ooxml_cells(
        package, sheet_path, shared_strings, date_style_indexes, date_1904,
    ):
        field_index = column_index - 1
        if row_index <= header_row or not (0 <= field_index < len(fields)):
            continue
        if sample_counts[field_index] < 500:
            sample_counts[field_index] += 1
            sample_types[field_index][value_type(value)] += 1
            sample_distinct[field_index].add(text_value(value))
        if field_index in time_stats:
            stat = time_stats[field_index]
            stat["nonempty"] += 1
            parsed = parse_date_value(value)
            if parsed and datetime(1990, 1, 1) <= parsed.replace(tzinfo=None) <= datetime(2100, 12, 31):
                comparable = parsed.replace(tzinfo=None)
                stat["parsed"] += 1
                stat["min"] = comparable if stat["min"] is None else min(stat["min"], comparable)
                stat["max"] = comparable if stat["max"] is None else max(stat["max"], comparable)

    profiles: list[dict[str, Any]] = []
    for index, field in enumerate(fields):
        counts = sample_types[index]
        count = sample_counts[index]
        profile: dict[str, Any] = {
            "field": field,
            "column": get_column_letter(index + 1),
            "sample_nonempty_count": count,
            "sample_types": dict(counts.most_common()),
            "dominant_sample_type": counts.most_common(1)[0][0] if counts else "空值",
        }
        if count:
            profile["sample_distinct_count"] = len(sample_distinct[index])
            profile["sample_unique_ratio"] = round(len(sample_distinct[index]) / count, 4)
        profiles.append(profile)

    time_ranges: list[dict[str, Any]] = []
    for index in sorted(time_indexes):
        stat = time_stats[index]
        item: dict[str, Any] = {
            "field": fields[index],
            "column": get_column_letter(index + 1),
            "nonempty_count": stat["nonempty"],
            "parsed_count": stat["parsed"],
        }
        if stat["parsed"]:
            item["min"] = stat["min"].date().isoformat()
            item["max"] = stat["max"].date().isoformat()
            item["parse_ratio"] = round(stat["parsed"] / max(1, stat["nonempty"]), 4)
        time_ranges.append(item)
    return profiles, time_ranges


def scan_xlsx(path: Path) -> list[dict[str, Any]]:
    sheets: list[dict[str, Any]] = []
    try:
        with ZipFile(path) as package:
            shared_strings = read_shared_strings(package)
            date_style_indexes = read_date_style_indexes(package)
            workbook_sheets, date_1904 = read_workbook_metadata(package)
            for workbook_sheet in workbook_sheets:
                sheet_path = workbook_sheet["path"]
                if not sheet_path or sheet_path not in package.namelist():
                    raise ValueError(f"找不到工作表 XML：{sheet_path or workbook_sheet['name']}")
                preview_rows, stats, merge_ranges = scan_worksheet_first_pass(
                    package, sheet_path, shared_strings, date_style_indexes, date_1904,
                )
                header_row, header_rows, fields = detect_header(preview_rows)
                profiles, time_ranges = scan_worksheet_columns(
                    package, sheet_path, shared_strings, date_style_indexes, date_1904,
                    header_row, fields,
                )
                relative_path = str(path.relative_to(SOURCE_ROOT))
                modules, objects, keys, sensitive = infer_metadata(relative_path, fields)
                state = workbook_sheet["state"]
                hidden = state != "visible"
                issues = quality_issues(
                    [], header_row, fields, stats["effective_rows"], stats["effective_cols"],
                    stats["formula_cells"], len(merge_ranges), time_ranges, hidden,
                )
                sheets.append({
                    "sheet_name": workbook_sheet["name"],
                    "visibility": state,
                    **stats,
                    "header_row": header_row,
                    "header_rows": header_rows,
                    "fields": fields,
                    "column_profiles": profiles,
                    "merged_cells": {
                        "count": len(merge_ranges),
                        "ranges_preview": merge_ranges[:30],
                    },
                    "time_fields": time_ranges,
                    "business_objects": objects,
                    "possible_keys": keys,
                    "data_purpose": infer_purpose(relative_path, modules, objects),
                    "supported_modules": modules,
                    "directly_useful_for_product_sales_inventory": "产品/销售/库存" in modules,
                    "sensitive_fields": sensitive,
                    "quality_issues": issues,
                })
    except BadZipFile as exc:
        raise ValueError("不是有效的 OOXML/ZIP 工作簿") from exc
    return sheets


def infer_purpose(path_text: str, modules: list[str], objects: list[str]) -> str:
    path_lower = path_text.lower()
    if "广告" in path_text or "sponsored" in path_lower:
        return "Amazon 广告报表，用于分析广告活动、投放、搜索词、广告位、预算或归因效果"
    if "库存" in path_text or "备货" in path_text or "补货" in path_text:
        return "库存快照、补货测算或备货计划，用于库存风险、补货建议和供应链跟踪"
    if "物流" in path_text or "运输" in path_text or "仓储" in path_text or "出货" in path_text:
        return "物流、出货、运输时效/运费或仓储费用管理"
    if "利润" in path_text or "财务" in path_text:
        return "销售财务与利润测算，用于收入、成本、费用和利润分析"
    if "产品跟进" in path_text:
        return "运营人员按产品记录表现、问题、计划和跟进状态"
    if "动作调整" in path_text:
        return "运营动作与调整记录，用于策略追踪和后续复盘"
    if "关键词" in path_text:
        return "关键词研究与排名/流量洞察"
    if "竞品" in path_text:
        return "竞品、类目与市场表现分析"
    if "复盘" in path_text or "周报" in path_text or "月报" in path_text:
        return "阶段经营总结、问题分析与行动复盘"
    if modules:
        return "支持" + "、".join(modules) + "相关分析"
    if objects:
        return "包含" + "、".join(objects) + "等业务数据"
    return "用途需结合业务上下文进一步确认"


def read_delimited(path: Path) -> tuple[list[list[Any]], dict[str, Any]]:
    encoding = detect_encoding(path)
    raw = path.read_text(encoding=encoding, errors="replace")
    sample = raw[:100_000]
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        pass
    rows = [row for row in csv.reader(raw.splitlines(), delimiter=delimiter)]
    return rows, {"encoding": encoding, "delimiter": delimiter}


def read_html_tables(path: Path) -> list[tuple[str, list[list[Any]]]]:
    encoding = detect_encoding(path)
    text = path.read_text(encoding=encoding, errors="replace")
    root = lxml_html.fromstring(text)
    result: list[tuple[str, list[list[Any]]]] = []
    for table_index, table in enumerate(root.xpath("//table"), start=1):
        rows: list[list[Any]] = []
        for tr in table.xpath(".//tr"):
            cells = tr.xpath("./th|./td")
            values = [" ".join(cell.text_content().split()) for cell in cells]
            if values:
                rows.append(values)
        result.append((f"HTML表{table_index}", rows))
    if not result:
        # Preserve a file-level entry even when the page has no actual table.
        result.append(("HTML正文", []))
    return result


def scan_tabular_rows(path: Path, sheet_name: str, rows: list[list[Any]], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    max_row = 0
    max_col = 0
    nonempty = 0
    for row_index, row in enumerate(rows, start=1):
        row_nonempty = [index for index, value in enumerate(row, start=1) if not is_blank(value)]
        if row_nonempty:
            max_row = row_index
            max_col = max(max_col, max(row_nonempty))
            nonempty += len(row_nonempty)
    rows = rows[:max_row]
    header_row, header_rows, fields = detect_header(rows[:80])
    profiles = make_column_profiles(rows, header_row, fields)
    time_ranges = find_time_ranges(rows, header_row, fields)
    modules, objects, keys, sensitive = infer_metadata(str(path.relative_to(SOURCE_ROOT)), fields)
    issues = quality_issues(rows, header_row, fields, max_row, max_col, 0, 0, time_ranges, False)
    result = {
        "sheet_name": sheet_name,
        "visibility": "visible",
        "effective_rows": max_row,
        "effective_cols": max_col,
        "nonempty_cells": nonempty,
        "formula_cells": 0,
        "error_cells": 0,
        "header_row": header_row,
        "header_rows": header_rows,
        "fields": fields,
        "column_profiles": profiles,
        "merged_cells": {"count": 0, "ranges_preview": []},
        "time_fields": time_ranges,
        "business_objects": objects,
        "possible_keys": keys,
        "data_purpose": infer_purpose(str(path.relative_to(SOURCE_ROOT)), modules, objects),
        "supported_modules": modules,
        "directly_useful_for_product_sales_inventory": "产品/销售/库存" in modules,
        "sensitive_fields": sensitive,
        "quality_issues": issues,
    }
    if extra:
        result["parser_metadata"] = extra
    return result


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return "Excel 工作簿"
    if suffix in {".csv", ".tsv"}:
        return "分隔文本"
    if suffix in {".html", ".htm"}:
        return "HTML"
    return suffix.lstrip(".").upper()


def scan_file(path: Path) -> dict[str, Any]:
    relative = str(path.relative_to(SOURCE_ROOT))
    stat = path.stat()
    item: dict[str, Any] = {
        "relative_path": relative,
        "file_name": path.name,
        "file_type": file_kind(path),
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "size_human": human_size(stat.st_size),
        "sha256": sha256(path),
        "sheets": [],
        "scan_status": "ok",
        "scan_error": None,
    }
    try:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            item["sheets"] = scan_xlsx(path)
        elif path.suffix.lower() in {".csv", ".tsv"}:
            rows, metadata = read_delimited(path)
            item["sheets"] = [scan_tabular_rows(path, "CSV", rows, metadata)]
        elif path.suffix.lower() in {".html", ".htm"}:
            tables = read_html_tables(path)
            item["sheets"] = [scan_tabular_rows(path, name, rows) for name, rows in tables]
    except Exception as exc:
        item["scan_status"] = "error"
        item["scan_error"] = f"{type(exc).__name__}: {exc}"
    return item


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_duplicate_template_groups(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for file_item in files:
        for sheet in file_item["sheets"]:
            normalized = [re.sub(r"\s+", "", f).lower() for f in sheet.get("fields", []) if f]
            if len(normalized) < 2:
                continue
            signature = hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:12]
            sheet["field_signature"] = signature
            groups[signature].append((file_item, sheet))
    duplicate_groups = []
    group_number = 0
    for signature, members in sorted(groups.items()):
        distinct_files = {f["relative_path"] for f, _ in members}
        if len(members) < 2 or len(distinct_files) < 2:
            continue
        group_number += 1
        group_id = f"T{group_number:03d}"
        refs = [{"file": f["relative_path"], "sheet": s["sheet_name"]} for f, s in members]
        for _, sheet in members:
            sheet["duplicate_template_group"] = group_id
            sheet["quality_issues"].append(f"字段结构与其他文件重复（模板组 {group_id}）")
        duplicate_groups.append({"group_id": group_id, "field_signature": signature, "members": refs})
    return duplicate_groups


def build_summary(files: list[dict[str, Any]], duplicate_groups: list[dict[str, Any]]) -> dict[str, Any]:
    sheets = [sheet for file_item in files for sheet in file_item.get("sheets", [])]
    by_type = Counter(file_item["extension"] for file_item in files)
    module_counts = Counter(module for sheet in sheets for module in sheet.get("supported_modules", []))
    return {
        "file_count": len(files),
        "sheet_or_table_count": len(sheets),
        "files_by_extension": dict(sorted(by_type.items())),
        "scan_ok_files": sum(f["scan_status"] == "ok" for f in files),
        "scan_error_files": sum(f["scan_status"] != "ok" for f in files),
        "empty_sheets": sum("空表" in s.get("quality_issues", []) for s in sheets),
        "header_only_sheets": sum("仅含表头，无明细数据" in s.get("quality_issues", []) for s in sheets),
        "hidden_sheets": sum(s.get("visibility") != "visible" for s in sheets),
        "formula_cells": sum(s.get("formula_cells", 0) for s in sheets),
        "merged_cells": sum(s.get("merged_cells", {}).get("count", 0) for s in sheets),
        "direct_product_sales_inventory_sheets": sum(s.get("directly_useful_for_product_sales_inventory", False) for s in sheets),
        "module_sheet_counts": dict(module_counts.most_common()),
        "duplicate_template_group_count": len(duplicate_groups),
    }


def main() -> int:
    files = [
        path for path in SOURCE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in VALID_EXTENSIONS
        and path.name != ".DS_Store"
        and not path.name.startswith("~$")
    ]
    files.sort(key=lambda p: str(p.relative_to(SOURCE_ROOT)))
    scanned = []
    for index, path in enumerate(files, start=1):
        print(f"[{index:02d}/{len(files):02d}] {path.relative_to(SOURCE_ROOT)}", flush=True)
        scanned.append(scan_file(path))
    duplicate_groups = add_duplicate_template_groups(scanned)
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(SOURCE_ROOT),
        "scope_note": "只读扫描；排除 .DS_Store、~$ 临时锁文件及不支持的文件类型。样例仅记录类型与计数，不复制客户明细值。",
        "summary": build_summary(scanned, duplicate_groups),
        "duplicate_template_groups": duplicate_groups,
        "files": scanned,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
