#!/usr/bin/env python3
"""合并客户数据源广告/非广告分片，生成统一 JSON 与 Markdown 总索引。"""

from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
INDEX_ROOT = HERE.parent
NON_AD_JSON = HERE / "客户数据源索引-非广告分片.json"
AD_JSON = HERE / "客户数据源索引-广告分片.json"
OUTPUT_JSON = INDEX_ROOT / "客户数据源索引.json"
OUTPUT_MD = INDEX_ROOT / "02-客户原始数据源索引.md"
SCANNER = HERE / "scan_customer_sources.py"


def load_scanner():
    spec = importlib.util.spec_from_file_location("source_scanner", SCANNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_old_template_annotations(files: list[dict]) -> None:
    for file_item in files:
        for sheet in file_item.get("sheets", []):
            sheet.pop("duplicate_template_group", None)
            sheet.pop("field_signature", None)
            sheet["quality_issues"] = [
                issue for issue in sheet.get("quality_issues", [])
                if not issue.startswith("字段结构与其他文件重复（模板组")
            ]


def exact_duplicate_groups(files: list[dict]) -> list[dict]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for item in files:
        by_hash[item["sha256"]].append(item["relative_path"])
    return [
        {"sha256": digest, "members": sorted(members)}
        for digest, members in sorted(by_hash.items())
        if len(members) > 1
    ]


def time_summary(sheet: dict) -> str:
    ranges = []
    for item in sheet.get("time_fields", []):
        start = item.get("min_date") or item.get("min")
        end = item.get("max_date") or item.get("max")
        if start or end:
            ranges.append(f"{item.get('field', '')}: {start or '?'} → {end or '?'}")
    return "<br>".join(ranges[:3]) or "—"


def md_escape(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", "<br>")


def top_group(relative_path: str) -> str:
    return relative_path.split("/", 1)[0]


def make_markdown(payload: dict) -> str:
    files = payload["files"]
    sheets = [sheet for item in files for sheet in item.get("sheets", [])]
    summary = payload["summary"]
    exact_groups = payload["exact_duplicate_file_groups"]
    template_groups = payload["duplicate_template_groups"]
    total_bytes = sum(item["size_bytes"] for item in files)

    by_group: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "sheets": 0, "bytes": 0})
    for item in files:
        group = top_group(item["relative_path"])
        by_group[group]["files"] += 1
        by_group[group]["sheets"] += len(item.get("sheets", []))
        by_group[group]["bytes"] += item["size_bytes"]

    lines = [
        "# 客户原始数据源索引",
        "",
        f"生成时间：{payload['generated_at']}  ",
        f"源目录：`{payload['source_root']}`  ",
        "用途：为 Bamboocool Demo 与后续模块设计提供文件、工作表、字段、时间范围、关联键和数据质量入口。",
        "",
        "> 本索引只读扫描源文件，不修改客户工作簿。排除 `.DS_Store`、`~$` 锁文件和不支持的类型。数据用途是根据文件、Sheet 和字段结构的索引性描述，不等于已确认的客户业务口径。",
        "",
        "## 1. 全量覆盖",
        "",
        f"- 有效文件：**{summary['file_count']}** 个，总大小约 **{total_bytes / 1024 / 1024:.1f} MB**；",
        f"- Sheet / HTML 表：**{summary['sheet_or_table_count']}** 个；",
        f"- 成功扫描：**{summary['scan_ok_files']}** 个，失败：**{summary['scan_error_files']}** 个；",
        f"- 空表：**{summary.get('empty_sheets', 0)}** 个，仅表头表：**{summary.get('header_only_sheets', 0)}** 个，隐藏 Sheet：**{summary.get('hidden_sheets', 0)}** 个；",
        f"- 公式单元格：**{summary.get('formula_cells', 0):,}**，合并单元格：**{summary.get('merged_cells', 0):,}**；",
        f"- 完全相同文件组：**{len(exact_groups)}**，重复字段模板组：**{len(template_groups)}**。",
        "",
        "详细字段和列类型见 [非广告数据源分册](02A-非广告数据源索引分册.md) 与 [广告数据源分册](02B-广告数据源索引分册.md)；机器可读全量结果见 `客户数据源索引.json`。",
        "",
        "## 2. 目录覆盖",
        "",
        "| 目录 / 主题 | 文件 | Sheet/表 | 大小 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for group, stats in sorted(by_group.items()):
        lines.append(f"| {md_escape(group)} | {stats['files']} | {stats['sheets']} | {stats['bytes'] / 1024 / 1024:.1f} MB |")

    lines += [
        "",
        "## 3. 全部文件索引",
        "",
        "| 相对路径 | 类型 | 大小 | Sheet/表 | 实际数据规模 | 状态 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in files:
        shape = ", ".join(
            f"{s['sheet_name']} {s.get('effective_rows', 0)}×{s.get('effective_cols', 0)}"
            for s in item.get("sheets", [])[:4]
        )
        if len(item.get("sheets", [])) > 4:
            shape += f" 等 {len(item['sheets'])} 表"
        lines.append(
            f"| `{md_escape(item['relative_path'])}` | {item['file_type']} | {item['size_human']} | "
            f"{len(item.get('sheets', []))} | {md_escape(shape)} | {item['scan_status']} |"
        )

    lines += [
        "",
        "## 4. Sheet / 表级索引",
        "",
        "| 文件 | Sheet/表 | 可见性 | 有效行×列 | 表头 | 时间范围 | 主要用途 | 质量提示 |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for item in files:
        for sheet in item.get("sheets", []):
            issues = "；".join(sheet.get("quality_issues", [])[:3]) or "—"
            lines.append(
                f"| `{md_escape(item['relative_path'])}` | {md_escape(sheet['sheet_name'])} | "
                f"{md_escape(sheet.get('visibility', 'visible'))} | "
                f"{sheet.get('effective_rows', 0)}×{sheet.get('effective_cols', 0)} | "
                f"{sheet.get('header_row') or '—'} | {md_escape(time_summary(sheet))} | "
                f"{md_escape(sheet.get('data_purpose', ''))} | {md_escape(issues)} |"
            )

    lines += [
        "",
        "## 5. 完全重复文件",
        "",
    ]
    if exact_groups:
        for index, group in enumerate(exact_groups, start=1):
            lines.append(f"### D{index:03d}")
            lines.append("")
            for member in group["members"]:
                lines.append(f"- `{member}`")
            lines.append("")
    else:
        lines += ["未发现 SHA-256 完全相同的文件。", ""]

    lines += [
        "## 6. 重复字段模板",
        "",
        "模板重复代表表头结构相同，不代表数据内容完全相同。",
        "",
        "| 模板组 | 成员数 | 成员预览 |",
        "| --- | ---: | --- |",
    ]
    for group in template_groups:
        preview = "<br>".join(f"{m['file']} / {m['sheet']}" for m in group["members"][:5])
        if len(group["members"]) > 5:
            preview += f"<br>等 {len(group['members'])} 个"
        lines.append(f"| {group['group_id']} | {len(group['members'])} | {md_escape(preview)} |")

    lines += [
        "",
        "## 7. 索引字段说明",
        "",
        "每个 Sheet / 表在 JSON 中统一记录：",
        "",
        "- `effective_rows` / `effective_cols`：有实际单元格内容的真实数据区，不使用 Excel 格式化空行宣告的虚假维度；",
        "- `header_row` / `header_rows` / `fields`：识别的主表头、多层表头和展开后的字段；",
        "- `column_profiles`：每列的值类型、非空数和样本类型统计；",
        "- `time_fields`：可能的时间字段、可解析比例和最小/最大日期；",
        "- `possible_keys`：ASIN、SKU、FNSKU、广告活动、关键词、日期等候选关联键；",
        "- `business_objects` / `supported_modules` / `data_purpose`：索引性业务描述，后续需再与页面能力匹配；",
        "- `formula_cells` / `merged_cells` / `quality_issues`：导入时需处理的公式、合并表头、空表、混合日期、缺失字段等问题；",
        "- `sha256` / `duplicate_template_group`：完全重复文件与重复字段模板识别。",
        "",
        "## 8. 使用边界",
        "",
        "- 索引中的数量和时间范围用于判断数据能力，不代表页面应直接展示客户原始值；",
        "- 同一业务指标在不同文件中可能存在口径、币种、归因周期和更新时间差异；",
        "- 公式密集工作簿需同时保留公式和缓存结果，不能只取当前显示值；",
        "- 所有 Demo 构造数据必须标记为 `simulated`，由规则生成的结果标记为 `derived`，不将原表占位、估算值或历史模板当作客户事实。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    scanner = load_scanner()
    non_ad = load_json(NON_AD_JSON)
    ad = load_json(AD_JSON)
    files = copy.deepcopy(non_ad["files"] + ad["files"])
    files.sort(key=lambda item: item["relative_path"])
    clean_old_template_annotations(files)
    duplicate_templates = scanner.add_duplicate_template_groups(files)
    exact_duplicates = exact_duplicate_groups(files)
    summary = scanner.build_summary(files, duplicate_templates)
    summary["header_only_sheets"] = sum(
        any("仅含表头" in issue for issue in sheet.get("quality_issues", []))
        for item in files for sheet in item.get("sheets", [])
    )
    payload = {
        "schema_version": "1.1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": non_ad["source_root"],
        "scope_note": "广告与非广告分片使用同一稀疏 OOXML/CSV/HTML 只读扫描 schema，此文件为全量合并与跨分片去重结果。",
        "summary": summary,
        "exact_duplicate_file_groups": exact_duplicates,
        "duplicate_template_groups": duplicate_templates,
        "files": files,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(make_markdown(payload), encoding="utf-8")
    print(json.dumps({
        "json": str(OUTPUT_JSON),
        "markdown": str(OUTPUT_MD),
        "summary": summary,
        "exact_duplicates": len(exact_duplicates),
        "template_groups": len(duplicate_templates),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
