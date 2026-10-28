"""CSV and XLSX export of report dictionaries.

Security: any text cell beginning with = + - @ (or tab/CR) is prefixed with an apostrophe
so spreadsheet programs never execute it as a formula (CSV/formula injection).
Money is written as real numbers in XLSX with Indian digit grouping, and as plain
decimal strings in CSV."""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Excel number format giving Indian grouping for positive amounts: 1,25,00,000.00
# (Excel allows only two conditions, so negative amounts fall back to 1,25,000-style
#  western grouping, still with the correct value and sign.)
INR_FORMAT = '[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00'
DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe_text(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(DANGEROUS) else s


def _filename(report: dict, ext: str) -> str:
    return f"{report['company']['code']}_{report['report']}_{report['from']}_{report['to']}.{ext}"


def to_csv(report: dict) -> tuple[bytes, str]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"{report['company']['name']} — {report['title']}"])
    w.writerow([f"Period {report['from']} to {report['to']}"])
    w.writerow([])
    cols = report["columns"]
    w.writerow([c["label"] for c in cols])
    for row in report["rows"]:
        w.writerow([(row.get(c["key"]) or "") if c["type"] in ("money", "number") else safe_text(row.get(c["key"]))
                    for c in cols])
    if report["totals"]:
        w.writerow([("Total" if i == 0 else report["totals"].get(c["key"]) or "") for i, c in enumerate(cols)])
    for n in report["notes"]:
        w.writerow([safe_text(n)])
    # UTF-8 with BOM so Excel shows ₹ and Marathi names correctly
    return buf.getvalue().encode("utf-8-sig"), _filename(report, "csv")


def to_xlsx(report: dict) -> tuple[bytes, str]:
    wb = Workbook()
    ws = wb.active
    ws.title = report["title"][:31].replace("/", "-")
    cols = report["columns"]
    ws.append([f"{report['company']['name']} — {report['title']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Period {report['from']} to {report['to']} · generated {date.today()} by {report.get('generated_by') or ''}"])
    ws.append([])
    ws.append([c["label"] for c in cols])
    header_row = ws.max_row
    for cell in ws[header_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    def put(row_values: dict, bold=False):
        values = []
        for c in cols:
            v = row_values.get(c["key"])
            if c["type"] == "money" and v not in (None, ""):
                values.append(Decimal(v))
            elif c["type"] == "number" and v not in (None, ""):
                values.append(v)
            elif c["type"] == "date" and v:
                values.append(date.fromisoformat(v[:10]))
            else:
                values.append(safe_text(v) if v is not None else None)
        ws.append(values)
        r = ws.max_row
        for i, c in enumerate(cols, start=1):
            cell = ws.cell(row=r, column=i)
            if c["type"] == "money":
                cell.number_format = INR_FORMAT
            elif c["type"] == "date":
                cell.number_format = "DD-MM-YYYY"
            if bold:
                cell.font = Font(bold=True)

    for row in report["rows"]:
        put(row)
    if report["totals"]:
        put({**report["totals"], cols[0]["key"]: "Total"}, bold=True)
    ws.append([])
    for n in report["notes"]:
        ws.append([safe_text(n)])
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    for i, c in enumerate(cols, start=1):
        width = 16 if c["type"] == "money" else 12 if c["type"] in ("date", "number") else 24
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(cols))}{header_row + len(report['rows'])}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), _filename(report, "xlsx")
