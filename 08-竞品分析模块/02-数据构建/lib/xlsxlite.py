#!/usr/bin/env python3
"""Minimal read-only xlsx/csv reader for source-table reconnaissance.

Stdlib + lxml only (no openpyxl in this environment).
Never writes to the source files.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import zipfile

from lxml import etree

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"m": M, "r": R}

_EPOCH = _dt.date(1899, 12, 30)  # Excel 1900 system with the leap-year bug


def serial_to_date(value):
    """Convert an Excel date serial to an ISO date string, or None."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 80000:
        return None
    return (_EPOCH + _dt.timedelta(days=int(n))).isoformat()


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = etree.fromstring(data)
    out = []
    for si in root.findall("m:si", NS):
        out.append("".join(t.text or "" for t in si.iter(f"{{{M}}}t")))
    return out


def sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return [(sheet_name, zip_path), ...] in workbook order."""
    wb = etree.fromstring(zf.read("xl/workbook.xml"))
    rels = etree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid = {rel.get("Id"): rel.get("Target") for rel in rels}
    out = []
    for sh in wb.find("m:sheets", NS):
        target = rid.get(sh.get(f"{{{R}}}id"), "")
        if target.startswith("/xl/"):
            path = target[1:]
        elif target.startswith("xl/"):
            path = target
        else:
            path = "xl/" + target.lstrip("/")
        out.append((sh.get("name"), path))
    return out


def _col_index(ref: str) -> int:
    """'BC12' -> 54 (1-based column number)."""
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n


def iter_rows(path: str, sheet_index: int = 0, limit: int | None = None):
    """Yield rows as lists of raw cell values (str or float). Streaming."""
    with zipfile.ZipFile(path) as zf:
        strings = _shared_strings(zf)
        sheet_list = sheets(zf)
        if sheet_index >= len(sheet_list):
            return
        _, zpath = sheet_list[sheet_index]
        with zf.open(zpath) as fh:
            count = 0
            for _, elem in etree.iterparse(fh, events=("end",), tag=f"{{{M}}}row"):
                cells: dict[int, object] = {}
                for c in elem.findall(f"{{{M}}}c"):
                    ci = _col_index(c.get("r") or "A1")
                    ctype = c.get("t")
                    if ctype == "inlineStr":
                        is_el = c.find(f"{{{M}}}is")
                        val = "".join(
                            t.text or "" for t in is_el.iter(f"{{{M}}}t")
                        ) if is_el is not None else None
                    else:
                        v = c.find(f"{{{M}}}v")
                        val = v.text if v is not None else None
                        if ctype == "s" and val is not None:
                            idx = int(val)
                            val = strings[idx] if idx < len(strings) else None
                        elif val is not None and ctype is None:
                            try:
                                val = float(val)
                            except ValueError:
                                pass
                    if val is not None:
                        cells[ci] = val
                width = max(cells) if cells else 0
                yield [cells.get(i) for i in range(1, width + 1)]
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]
                count += 1
                if limit is not None and count >= limit:
                    return


def sheet_summary(path: str) -> list[dict]:
    """Return per-sheet name, row count and first non-empty row (header)."""
    with zipfile.ZipFile(path) as zf:
        names = [n for n, _ in sheets(zf)]
    out = []
    for i, name in enumerate(names):
        rows = 0
        header = None
        for row in iter_rows(path, i):
            rows += 1
            if header is None and any(v is not None for v in row):
                header = [str(v) if v is not None else "" for v in row]
        out.append({"sheet": name, "rows": rows, "header": header or []})
    return out


def read_csv_head(path: str, limit: int = 3, encoding: str = "utf-8-sig"):
    """Return (header, sample_rows, total_rows) for a csv file."""
    with io.open(path, encoding=encoding, errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        return [], [], 0
    return rows[0], rows[1:1 + limit], len(rows) - 1
