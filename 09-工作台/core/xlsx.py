"""最小 xlsx 写出器 · 只用标准库

为什么手写：工作台不引第三方库（openpyxl / xlsxwriter 都不引），
而 xlsx 本质就是一个 zip 装几份 XML，标准库的 zipfile 够用。
读的那一侧另有一份 04-广告分析模块/00-源表勘查/xlsxlite.py，两者不共用，
也不要合并 —— 读和写的取舍不一样。

为什么必须是真 xlsx 而不是 CSV：2026-08-31 会上王楠说「他给其他部门下单也是用文件下单」。
CSV 在中文 Excel 里会因为编码问题变乱码（要么带 BOM 要么让人手选编码），
而且丢掉数字格式和列宽 —— 拿去下单的文件不能长这样。

实现取舍：
  · 字符串用 inlineStr，不建 sharedStrings.xml。省一份 XML，代价是重复字符串不去重，
    对几千行的导出无所谓。
  · styles.xml 只留三种：表头加粗、日期、两位小数。够用就不扩。
  · 不写 calcChain / theme / docProps，Excel 与 Numbers 都能正常打开。
"""

from __future__ import annotations

import datetime as _dt
import zipfile
from io import BytesIO
from typing import Any, Iterable, Sequence

# XML 里非法的控制字符（除了 \t \n \r）。Excel 遇到它们会直接报文件损坏。
_ILLEGAL = {c: "" for c in range(0x20) if c not in (0x09, 0x0A, 0x0D)}


def _esc(v: str) -> str:
    return (
        v.translate(_ILLEGAL)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _col(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA"""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# Excel 的日期是「1899-12-30 起的天数」。1900 那个闰年 bug 就在这个基准里，
# 用 12-30 而不是 12-31 正是为了对齐它，别改成 12-31。
_EPOCH = _dt.date(1899, 12, 30)


def _cell(ref: str, v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):                       # 必须在 int 之前判，bool 是 int 的子类
        return f'<c r="{ref}" t="inlineStr"><is><t>{"是" if v else "否"}</t></is></c>'
    if isinstance(v, _dt.date) and not isinstance(v, _dt.datetime):
        return f'<c r="{ref}" s="2"><v>{(v - _EPOCH).days}</v></c>'
    if isinstance(v, int):
        return f'<c r="{ref}"><v>{v}</v></c>'
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):   # NaN / inf 落成文本
            return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
        return f'<c r="{ref}" s="3"><v>{v!r}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{_esc(str(v))}</t></is></c>'


def _sheet_xml(headers: Sequence[str], rows: Iterable[Sequence[Any]],
               widths: Sequence[int] | None) -> str:
    # 元素顺序是硬要求：cols 必须在 sheetData 之前，sheetViews 必须在 cols 之前。
    # 顺序错了 Excel 报「文件已损坏」，而且不告诉你错在哪。
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        # 冻结首行，滚动时表头不跑
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>",
    ]
    if widths:
        out.append("<cols>")
        for i, w in enumerate(widths):
            out.append(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>')
        out.append("</cols>")
    out.append("<sheetData>")

    cells = "".join(
        f'<c r="{_col(i)}1" t="inlineStr" s="1"><is><t>{_esc(str(h))}</t></is></c>'
        for i, h in enumerate(headers)
    )
    out.append(f'<row r="1">{cells}</row>')

    n = 1
    for r in rows:
        n += 1
        cells = "".join(_cell(f"{_col(i)}{n}", v) for i, v in enumerate(r))
        if cells:
            out.append(f'<row r="{n}">{cells}</row>')

    out.append("</sheetData></worksheet>")
    return "".join(out)


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts>
<fonts count="2">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><name val="Calibri"/></font>
</fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="2" fontId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs>
</styleSheet>"""


def from_records(name: str, records: Iterable[dict],
                 columns: Sequence[tuple], widths: Sequence[int] | None = None) -> dict:
    """把一串字典按列规格摊成一张表。

    columns 是 [(字段名, 表头), ...] 或 [(字段名, 表头, 处理函数), ...]。
    **列必须显式列出，不许拿 keys() 自动铺**：自动铺会把 run_id、
    evidence_id、*_cell 这类内部字段一起导给客户，而且哪天载荷多一个键，
    导出的文件就悄悄多一列。

    日期串（YYYY-MM-DD）自动转成真日期，这样 Excel 里能排序和筛选；
    转不了的原样留字符串。
    """
    import datetime as _d

    def conv(v):
        if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
            try:
                return _d.date.fromisoformat(v)
            except ValueError:
                return v
        if isinstance(v, (list, tuple)):
            return "、".join(str(x) for x in v if x is not None)
        if isinstance(v, dict):
            return ""                      # 嵌套结构不摊平，要就单独开一页
        return v

    rows = []
    for r in records:
        row = []
        for col in columns:
            key, fn = col[0], (col[2] if len(col) > 2 else None)
            v = r.get(key)
            row.append(conv(fn(v, r) if fn else v))
        rows.append(row)
    return {"name": name, "headers": [c[1] for c in columns],
            "rows": rows, "widths": list(widths) if widths else None}


def build(sheets: Sequence[dict]) -> bytes:
    """把若干张表写成一个 xlsx 的字节串。

    每张表是 {"name": 页名, "headers": [...], "rows": [[...], ...], "widths": [...]}
    widths 可省。页名里的 : \\ / ? * [ ] 会被换成下划线 —— Excel 不接受这些字符，
    带进去会开不了文件，而且报的错跟页名毫无关系。
    """
    if not sheets:
        raise ValueError("至少要一张表")

    names, used = [], set()
    for i, s in enumerate(sheets):
        nm = str(s.get("name") or f"Sheet{i + 1}")
        for ch in ':\\/?*[]':
            nm = nm.replace(ch, "_")
        nm = nm[:31] or f"Sheet{i + 1}"
        base, k = nm, 2
        while nm in used:                      # 同名页会让 Excel 报损坏
            nm = f"{base[:28]}_{k}"
            k += 1
        used.add(nm)
        names.append(nm)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'spreadsheetml.worksheet+xml"/>'
            for i in range(len(sheets))
        )
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + overrides + "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            + "".join(
                f'<sheet name="{_esc(nm)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                for i, nm in enumerate(names)
            )
            + "</sheets></workbook>",
        )
        rels = "".join(
            f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
            for i in range(len(sheets))
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + rels
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/'
              'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>",
        )
        z.writestr("xl/styles.xml", _STYLES)
        for i, s in enumerate(sheets):
            z.writestr(
                f"xl/worksheets/sheet{i + 1}.xml",
                _sheet_xml(s.get("headers") or [], s.get("rows") or [], s.get("widths")),
            )
    return buf.getvalue()
