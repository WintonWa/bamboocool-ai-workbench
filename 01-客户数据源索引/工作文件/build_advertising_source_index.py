#!/usr/bin/env python3
"""Build the read-only 13.广告 source-data index and Markdown booklet."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
INDEX_ROOT = HERE.parent
SCANNER_PATH = HERE / "scan_customer_sources.py"
SLICE_ROOT = Path("/Users/linsen/BAM/数据源/AI广告对接数据-总20260803/13.广告")
JSON_OUTPUT = HERE / "客户数据源索引-广告分片.json"
MARKDOWN_OUTPUT = INDEX_ROOT / "02B-广告数据源索引分册.md"


def load_scanner():
    spec = importlib.util.spec_from_file_location("customer_source_scanner", SCANNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载共享 scanner：{SCANNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def md(value) -> str:
    if value is None:
        return "—"
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text.replace("|", "\\|").replace("`", "\\`")


def join_or_dash(values, separator: str = "、") -> str:
    clean = [str(value) for value in values if value not in (None, "")]
    return separator.join(clean) if clean else "—"


def format_type_counts(profile: dict) -> str:
    counts = profile.get("sample_types", {})
    if not counts:
        return "空值"
    return "、".join(f"{name} {count}" for name, count in counts.items())


def write_markdown(payload: dict) -> None:
    summary = payload["summary"]
    files = payload["files"]
    lines: list[str] = [
        "# 02B｜广告数据源索引分册",
        "",
        "> 本分册仅盘点客户原始目录 `13.广告/` 下的有效 XLSX/CSV 文件。扫描过程只读；排除 `.DS_Store`、`~$` 临时锁文件。样例信息只记录字段类型与计数，不复制客户明细数值。",
        "",
        "## 1. 分片汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 文件数 | {summary['file_count']} |",
        f"| Sheet/CSV 表数 | {summary['sheet_or_table_count']} |",
        f"| 扫描成功文件 | {summary['scan_ok_files']} |",
        f"| 扫描异常文件 | {summary['scan_error_files']} |",
        f"| 隐藏 Sheet | {summary['hidden_sheets']} |",
        f"| 空表 | {summary['empty_sheets']} |",
        f"| 仅含表头、无明细的表 | {summary['header_only_sheets']} |",
        f"| 公式单元格 | {summary['formula_cells']} |",
        f"| 合并单元格 | {summary['merged_cells']} |",
        f"| 重复字段模板组 | {summary['duplicate_template_group_count']} |",
        "",
        "文件类型分布：" + "；".join(f"`{ext}` {count} 个" for ext, count in summary["files_by_extension"].items()) + "。",
        "",
        "## 2. 索引口径与质量规则",
        "",
        "- **有效行列**：只统计实际含值或公式的 OOXML 单元格；仅有样式的空单元格不会把行数膨胀到 Excel 末行。",
        "- **表头行**：由字段密度、文本比例和广告/业务字段关键词综合识别；多层表头会同时记录 `header_rows`。",
        "- **类型概况**：每列最多抽取前 500 个非空值，只保留类型计数、去重数和唯一率，不保留样例明细值。",
        "- **时间范围**：仅对名称疑似日期/时间/周期的字段解析；不能稳定解析时明确保留质量提示。",
        "- **公式与合并**：公式读取为公式文本，不把缓存结果当作原始输入；合并单元格列出数量及最多 30 个范围预览。",
        "- **可能键**：依据字段语义标记 ASIN、SKU、活动、广告组、关键词、搜索词、日期、站点等候选关联键，不承诺唯一性。",
        "- **敏感提示**：只按字段名识别联系人、账号、买家等潜在敏感信息；未显示真实值。",
        "- **模块判断**：描述数据可支持的业务域，不表示实施优先级或数据已经满足生产质量。",
        "",
        "## 3. 文件总览",
        "",
        "| # | 相对路径 | 类型 | 大小 | Sheet/表 | 状态 |",
        "|---:|---|---|---:|---:|---|",
    ]
    for index, file_item in enumerate(files, start=1):
        lines.append(
            f"| {index} | `{md(file_item['relative_path'])}` | {md(file_item['file_type'])} | "
            f"{md(file_item['size_human'])} | {len(file_item.get('sheets', []))} | {md(file_item['scan_status'])} |"
        )

    lines.extend(["", "## 4. 重复字段模板组", ""])
    groups = payload.get("duplicate_template_groups", [])
    if not groups:
        lines.append("本广告分片未识别出跨文件重复的完整字段签名。")
    else:
        lines.extend(["| 模板组 | 字段签名 | 成员 |", "|---|---|---|"])
        for group in groups:
            members = "<br>".join(
                f"`{md(member['file'])}` / `{md(member['sheet'])}`" for member in group["members"]
            )
            lines.append(f"| {group['group_id']} | `{group['field_signature']}` | {members} |")

    lines.extend(["", "## 5. 逐文件、逐 Sheet 明细", ""])
    for file_index, file_item in enumerate(files, start=1):
        lines.extend([
            f"### {file_index}. `{md(file_item['relative_path'])}`",
            "",
            f"- 文件类型：{md(file_item['file_type'])}（`{md(file_item['extension'])}`）",
            f"- 文件大小：{md(file_item['size_human'])}（{file_item['size_bytes']} bytes）",
            f"- SHA-256：`{file_item['sha256']}`",
            f"- 扫描状态：`{md(file_item['scan_status'])}`",
        ])
        if file_item.get("scan_error"):
            lines.append(f"- 扫描错误：{md(file_item['scan_error'])}")
        lines.append("")

        for sheet_index, sheet in enumerate(file_item.get("sheets", []), start=1):
            merged = sheet.get("merged_cells", {})
            time_fields = sheet.get("time_fields", [])
            lines.extend([
                f"#### {file_index}.{sheet_index} Sheet：`{md(sheet['sheet_name'])}`",
                "",
                f"- 可见性：`{md(sheet['visibility'])}`",
                f"- 有效范围：{sheet['effective_rows']} 行 × {sheet['effective_cols']} 列；非空/公式单元格 {sheet['nonempty_cells']} 个",
                f"- 表头：主表头第 {sheet['header_row'] if sheet['header_row'] is not None else '—'} 行；表头行集合 {join_or_dash(sheet.get('header_rows', []))}",
                f"- 公式：{sheet['formula_cells']} 个；错误类型单元格：{sheet['error_cells']} 个",
                f"- 合并单元格：{merged.get('count', 0)} 个；范围预览：{join_or_dash(merged.get('ranges_preview', []), '、')}",
                f"- 主要业务对象：{join_or_dash(sheet.get('business_objects', []))}",
                f"- 可能主键/关联键：{join_or_dash(sheet.get('possible_keys', []))}",
                f"- 数据用途：{md(sheet.get('data_purpose', '—'))}",
                f"- 可支持模块：{join_or_dash(sheet.get('supported_modules', []))}",
                f"- 产品/销售/库存模块直接相关标记：{'是' if sheet.get('directly_useful_for_product_sales_inventory') else '否'}",
                f"- 质量提示：{join_or_dash(sheet.get('quality_issues', []), '；')}",
                f"- 敏感字段提示：{join_or_dash(sheet.get('sensitive_fields', []), '；')}",
                f"- 字段签名：`{md(sheet.get('field_signature', '—'))}`；重复模板组：`{md(sheet.get('duplicate_template_group', '—'))}`",
                "",
                "**完整字段与样例类型概况**",
                "",
                "| 列 | 字段名 | 主导类型 | 样例类型计数 | 样本非空数 | 样本去重数 | 唯一率 |",
                "|---|---|---|---|---:|---:|---:|",
            ])
            profiles_by_column = {profile.get("column"): profile for profile in sheet.get("column_profiles", [])}
            if not sheet.get("fields"):
                lines.append("| — | 未可靠识别字段 | — | — | 0 | 0 | — |")
            else:
                for field_number, field_name in enumerate(sheet["fields"], start=1):
                    column = column_letter(field_number)
                    profile = profiles_by_column.get(column, {})
                    unique_ratio = profile.get("sample_unique_ratio")
                    unique_text = f"{unique_ratio:.1%}" if isinstance(unique_ratio, (int, float)) else "—"
                    lines.append(
                        f"| {column} | {md(field_name)} | {md(profile.get('dominant_sample_type', '—'))} | "
                        f"{md(format_type_counts(profile))} | {profile.get('sample_nonempty_count', 0)} | "
                        f"{profile.get('sample_distinct_count', 0)} | {unique_text} |"
                    )

            lines.extend(["", "**可能时间字段与范围**", ""])
            if not time_fields:
                lines.append("未识别出名称明确的时间字段。")
            else:
                lines.extend([
                    "| 列 | 字段 | 非空数 | 已解析数 | 最早 | 最晚 | 解析率 |",
                    "|---|---|---:|---:|---|---|---:|",
                ])
                for time_item in time_fields:
                    ratio = time_item.get("parse_ratio")
                    ratio_text = f"{ratio:.1%}" if isinstance(ratio, (int, float)) else "—"
                    lines.append(
                        f"| {md(time_item.get('column'))} | {md(time_item.get('field'))} | "
                        f"{time_item.get('nonempty_count', 0)} | {time_item.get('parsed_count', 0)} | "
                        f"{md(time_item.get('min'))} | {md(time_item.get('max'))} | {ratio_text} |"
                    )
            lines.append("")

    MARKDOWN_OUTPUT.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def column_letter(index: int) -> str:
    result = []
    while index:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def main() -> int:
    scanner = load_scanner()
    files = [
        path for path in SLICE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".xlsx", ".xlsm", ".csv", ".tsv"}
        and path.name != ".DS_Store"
        and not path.name.startswith("~$")
    ]
    files.sort(key=lambda path: str(path.relative_to(scanner.SOURCE_ROOT)))

    scanned = []
    for index, path in enumerate(files, start=1):
        print(f"[{index:02d}/{len(files):02d}] {path.relative_to(scanner.SOURCE_ROOT)}", flush=True)
        scanned.append(scanner.scan_file(path))

    duplicate_groups = scanner.add_duplicate_template_groups(scanned)
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(scanner.SOURCE_ROOT),
        "slice_root": str(SLICE_ROOT),
        "slice_name": "13.广告",
        "scope_note": "只读扫描 13.广告；排除 .DS_Store、~$ 临时锁文件及非 XLSX/CSV 文件。样例仅记录类型与计数，不复制客户明细值。",
        "summary": scanner.build_summary(scanned, duplicate_groups),
        "duplicate_template_groups": duplicate_groups,
        "files": scanned,
    }
    JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(payload)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
