#!/usr/bin/env python3
"""用共享 scan_customer_sources.py 的同一 schema 生成非广告分片。"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
INDEX_ROOT = HERE.parent
SHARED_SCANNER = HERE / "scan_customer_sources.py"
OUTPUT_JSON = HERE / "客户数据源索引-非广告分片.json"
OUTPUT_MD = INDEX_ROOT / "02A-非广告数据源索引分册.md"


def load_scanner():
    spec = importlib.util.spec_from_file_location("customer_source_scanner", SHARED_SCANNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载共享扫描器：{SHARED_SCANNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def esc(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def joined(values, empty="无") -> str:
    return "、".join(esc(value) for value in values) if values else empty


def render_sheet(sheet: dict) -> list[str]:
    lines = [f"#### Sheet：`{esc(sheet['sheet_name'])}`", ""]
    lines.extend([
        "| 维度 | 索引结果 |",
        "|---|---|",
        f"| 可见性 | {esc(sheet.get('visibility', '未知'))} |",
        f"| 有效数据区 | {sheet.get('effective_rows', 0)} 行 × {sheet.get('effective_cols', 0)} 列；非空单元格 {sheet.get('nonempty_cells', 0)} |",
        f"| 表头 | 主表头第 {sheet.get('header_row') or '未识别'} 行；表头层级 {joined(sheet.get('header_rows', []))} |",
        f"| 公式/错误 | 公式 {sheet.get('formula_cells', 0)}；错误单元格 {sheet.get('error_cells', 0)} |",
        f"| 合并单元格 | {sheet.get('merged_cells', {}).get('count', 0)}；范围示例：{joined(sheet.get('merged_cells', {}).get('ranges_preview', []))} |",
        f"| 业务对象 | {joined(sheet.get('business_objects', []))} |",
        f"| 可能关联键 | {joined(sheet.get('possible_keys', []))} |",
        f"| 数据用途 | {esc(sheet.get('data_purpose', ''))} |",
        f"| 支持模块 | {joined(sheet.get('supported_modules', []))} |",
        f"| 产品/销售/库存直接可用 | {'是' if sheet.get('directly_useful_for_product_sales_inventory') else '否'} |",
        f"| 敏感提示 | {joined(sheet.get('sensitive_fields', []))} |",
        f"| 质量提示 | {joined(sheet.get('quality_issues', []))} |",
        "",
    ])

    fields = sheet.get("fields", [])
    profiles = {profile.get("field"): profile for profile in sheet.get("column_profiles", [])}
    lines.extend(["完整字段与样本类型概况：", "", "| 序号 | 列 | 字段 | 主类型 | 样本类型计数 | 样本非空 | 样本去重 | 唯一率 |", "|---:|---|---|---|---|---:|---:|---:|"])
    if not fields:
        lines.append("| 1 | — | 未识别字段 | — | — | 0 | 0 | — |")
    for index, field in enumerate(fields, start=1):
        profile = profiles.get(field, {})
        type_counts = "、".join(f"{esc(k)}={v}" for k, v in profile.get("sample_types", {}).items()) or "无"
        unique_ratio = profile.get("sample_unique_ratio")
        ratio_text = f"{unique_ratio:.1%}" if isinstance(unique_ratio, (int, float)) else "—"
        lines.append(
            f"| {index} | {esc(profile.get('column', ''))} | {esc(field)} | "
            f"{esc(profile.get('dominant_sample_type', '空值'))} | {type_counts} | "
            f"{profile.get('sample_nonempty_count', 0)} | {profile.get('sample_distinct_count', 0)} | {ratio_text} |"
        )
    lines.append("")

    lines.extend(["时间字段范围：", "", "| 列 | 字段 | 非空数 | 可解析数 | 最小日期 | 最大日期 | 解析率 |", "|---|---|---:|---:|---|---|---:|"])
    time_fields = sheet.get("time_fields", [])
    if not time_fields:
        lines.append("| — | 未识别时间字段 | 0 | 0 | — | — | — |")
    for item in time_fields:
        parse_ratio = item.get("parse_ratio")
        ratio_text = f"{parse_ratio:.1%}" if isinstance(parse_ratio, (int, float)) else "—"
        lines.append(
            f"| {esc(item.get('column', ''))} | {esc(item.get('field', ''))} | "
            f"{item.get('nonempty_count', 0)} | {item.get('parsed_count', 0)} | "
            f"{esc(item.get('min', '—'))} | {esc(item.get('max', '—'))} | {ratio_text} |"
        )
    lines.append("")
    if sheet.get("duplicate_template_group"):
        lines.extend([f"重复模板组：`{sheet['duplicate_template_group']}`。", ""])
    return lines


def render_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        "# 客户数据源索引分册：非广告数据",
        "",
        "> 本分册由共享 `scan_customer_sources.py` 只读生成，范围为客户目录中除 `13.广告/` 之外的全部有效 XLSX/CSV/TSV/HTML；排除 `.DS_Store` 和 `~$` 临时锁文件。索引不复制客户明细值。",
        "",
        "## 扫描汇总",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 文件数 | {summary['file_count']} |",
        f"| Sheet/HTML 表数 | {summary['sheet_or_table_count']} |",
        f"| 成功文件 | {summary['scan_ok_files']} |",
        f"| 错误文件 | {summary['scan_error_files']} |",
        f"| 空 Sheet | {summary['empty_sheets']} |",
        f"| 隐藏 Sheet | {summary['hidden_sheets']} |",
        f"| 公式单元格 | {summary['formula_cells']} |",
        f"| 合并单元格 | {summary['merged_cells']} |",
        f"| 重复模板组 | {summary['duplicate_template_group_count']} |",
        "",
        "扩展名分布：" + joined([f"{key}={value}" for key, value in summary.get("files_by_extension", {}).items()]) + "。",
        "",
        "模块 Sheet 命中数：" + joined([f"{key}={value}" for key, value in summary.get("module_sheet_counts", {}).items()]) + "。",
        "",
        "## 重复字段模板组",
        "",
    ]
    duplicate_groups = payload.get("duplicate_template_groups", [])
    if not duplicate_groups:
        lines.append("未识别跨文件重复字段模板。")
    for group in duplicate_groups:
        lines.extend([
            f"### {group['group_id']}",
            "",
            f"- 字段签名：`{group['field_signature']}`",
            "- 成员：",
            "",
        ])
        lines.extend(f"  - `{esc(member['file'])}` → `{esc(member['sheet'])}`" for member in group["members"])
        lines.append("")

    lines.extend(["## 逐文件、逐 Sheet 索引", ""])
    for file_index, file_item in enumerate(payload["files"], start=1):
        lines.extend([
            f"### {file_index}. `{esc(file_item['relative_path'])}`",
            "",
            "| 文件属性 | 值 |",
            "|---|---|",
            f"| 类型 | {esc(file_item['file_type'])} (`{esc(file_item['extension'])}`) |",
            f"| 大小 | {esc(file_item['size_human'])} ({file_item['size_bytes']} bytes) |",
            f"| SHA-256 | `{file_item['sha256']}` |",
            f"| 扫描状态 | {esc(file_item['scan_status'])} |",
            f"| 扫描错误 | {esc(file_item.get('scan_error') or '无')} |",
            "",
        ])
        for sheet in file_item.get("sheets", []):
            lines.extend(render_sheet(sheet))
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    scanner = load_scanner()
    files = [
        path for path in scanner.SOURCE_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.lower() in scanner.VALID_EXTENSIONS
        and path.name != ".DS_Store"
        and not path.name.startswith("~$")
        and not str(path.relative_to(scanner.SOURCE_ROOT)).startswith("13.广告/")
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
        "scope_note": "只读扫描非广告文件；排除 13.广告/、.DS_Store、~$ 临时锁文件及不支持的文件类型。样例仅记录类型与计数，不复制客户明细值。",
        "summary": scanner.build_summary(scanned, duplicate_groups),
        "duplicate_template_groups": duplicate_groups,
        "files": scanned,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"WROTE {OUTPUT_JSON}")
    print(f"WROTE {OUTPUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
