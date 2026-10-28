# Phase 1 — Workbook Analysis

Source: `Company_Monthly_Balance_Sheet_Installments.xlsx` (inspected read-only from a copy; the original file was not modified).
Inspection method: every non-empty cell, formula (with cached value), number format, merged range, data validation, conditional format, comment, hidden row/column and freeze pane was dumped with openpyxl.

## 1. Workbook inventory

| Sheet (exact name) | Title cell (A1) | Used range | Real data? |
|---|---|---|---|
| `Sindhudurg ` (trailing space) | "A R Trading Company – Monthly Balance Sheet" | A1:N35 | Yes, partially (15 dated amounts, 4 expense lines) |
| `Rataagiri ` (trailing space, likely misspelling of *Ratnagiri*) | "A R Trading Company – Transaction Ledger" | A1:J186 | **No.** Template only: month labels and formulas, no transactions |

- No defined names, no Excel tables, no hidden rows/columns, no external links.
- Company details block (Sindhudurg A32:C35): Company = *A R Trading Company*, Address = *Sindhudurg*, Bank = *Bank of Baroda*.
- **No record in the workbook belongs to Jay Ganesh Transport.** Both sheet titles say A R Trading Company.

## 2. Sheet `Sindhudurg ` — Monthly Balance Sheet

### 2.1 Columns (row 2 headers)

| Col | Header | Contents found |
|---|---|---|
| A | Period | Month start dates (`mmm-yyyy`); "Total " in A13; "TOTAL / YEAR-END" in A24 |
| B | Date | Specific dates within the period |
| C | Opening Balance (₹) | 15 amounts (see 2.2). **Header does not match the contents** (see issue I-1) |
| D | Payments | Category text: Godown Bill, Diesel Payment, Employee Payment, Worker Payment (dropdown) |
| E | Monthly Bill (₹) | 4 amounts in rows 3–6 that sit beside the D categories, so they look like expense amounts |
| F | Other Expense / Charge (₹) | empty |
| G | Installment Received (₹) | empty |
| H | Expenses (₹) | empty |
| I | Cash Balance (₹) | empty (no formula) |
| J | Outstanding Bill (₹) | empty (no formula) |
| K | Period From | empty |
| L | Period To | empty |
| M | Period Shortfall (₹) | empty (no formula) |
| N | Status | empty |

### 2.2 Data rows (exact values)

| Row | Period (A) | Date (B) | Col C (₹) | D | E (₹) |
|---|---|---|---|---|---|
| 3 | Aug-2025 | 26-08-2025 | 1,98,000 | Godown Bill | 35,000 |
| 4 | | | | Diesel Payment | 90,000 |
| 5 | | | | Employee Payment | 40,000 |
| 6 | | | | Worker Payment | 75,000 |
| 8 | Sep-2025 | 04-09-2025 | 2,97,000 | | |
| 9 | | 16-09-2025 | 99,000 | | |
| 10 | Oct-2025 | 18-10-2025 | 4,95,000 | | |
| 11 | | 20-10-2025 | 3,00,000 | | |
| 12 | Dec-2025 | **14-12-2026** ⚠ | 2,94,000 | | |
| 13 | **Total** | | `=SUM(C3:C12)` → 16,83,000 | | |
| 15 | Jan-2026 | 20-01-2026 | 4,95,000 | | |
| 16 | | 31-01-2026 | 2,50,000 | | |
| 17 | March-2026 | 23-03-2026 | 5,00,000 | | |
| 18 | April-2026 | 01-04-2026 | 3,00,000 | | |
| 19 | | 22-04-2026 | 3,96,000 | | |
| 20 | **46174** ⚠ (= 01-06-2026) | **46181** ⚠ (= 08-06-2026) | 4,95,000 | | |
| 21 | | 29-06-2026 | 2,47,500 | | |
| 22 | Aug-2026 | 12-08-2026 | 6,93,000 | Godown Bill | |
| 23 | Sep-2026 | 04-09-2026 | 2,97,000 | | |
| 24 | **TOTAL / YEAR-END** | | `=C15+…+C23` → 36,73,500 | | |

Column C grand total (not computed in the workbook): **₹53,56,500**. Expense lines in E3:E6 total **₹2,40,000**.

### 2.3 Formulas

| Cell | Formula | Cached value | Note |
|---|---|---|---|
| C13 | `=SUM(C3:C12)` | 16,83,000 | Calendar-2025 subtotal. Cell format is Text (`@`) |
| C24 | `=C15+C16+C17+C18+C19+C20+C21+C22+C23` | 36,73,500 | Jan–Sep 2026. Not an Indian financial year (Apr–Mar) |
| E24 | `=SUM(E8:E20)` | 0 | **Excludes E3:E6** (₹2,40,000) and rows 21–23 |
| F24, G24, H24, M24 | `=SUM(x3:x20)` | 0 | Excludes rows 21–23 |
| I24 | `=I20` | empty | Closing cash taken from row 20, not the last row (23) |
| J24 | `=J20` | empty | Same problem as I24 |

No formulas exist for Cash Balance, Outstanding Bill, Period Shortfall or Status. **The workbook does not define how these are calculated.**

### 2.4 Validation and formatting

- D3:D23 dropdown: `Godown Bill, Employee Payment, Worker Payment, Diesel Payment`.
- E8:E23 has a *custom* validation whose formula is the same list text. That is not a valid formula, so this validation is broken.
- Conditional format: G3:G7 and H8:H23 turn red (`FFC7CE`) when the value is < 0.
- Freeze panes at A3. Merged ranges A1:N1 (title) and A27:N27–A30:N30 (blank note rows).

### 2.5 Cell comments (important)

| Cell | Comment |
|---|---|
| E3 | "Notebook: extra 33,000 line added to Jun–Jul 2025 bill (total 10,26,591). Label read as 'वारणा वापर' – please confirm." |
| E12 | "3-month period (Feb+Mar+Apr) as written in notebook." |
| E15 | "Notebook: 3,21,700 x 3 = 9,65,100; page shows 9,68,102 but the running total uses 9,65,102. Used 9,65,102." |
| E16 | "Notebook: 6,43,021 was struck out; corrected figure 6,42,827 used." |

The comments refer to **monthly bill figures transcribed from a paper notebook** (₹10,26,591, ₹9,65,102, ₹6,42,827) and to a Jun–Jul **2025** period. Those values are **not in the sheet now**: E3 holds 35,000 and E12/E15/E16 are empty. The bill data the comments describe appears to have been overwritten or deleted. The original notebook or an earlier copy of the file is needed.

## 3. Sheet `Rataagiri ` — Transaction Ledger (template)

| Col | Header | Contents |
|---|---|---|
| A | Date | Only month labels copied from Sindhudurg (A3–A19); "Total " in A9, "TOTAL / YEAR-END" in A20 |
| B | Month | B21:B186: `=IF(A21="","",TEXT(A21,"mmmm"))` (166 formulas, all blank) |
| C | Type | Dropdown `Installment, Expense, Bill` (C3:C186) |
| D | Description / Particulars | empty |
| E | Bill Raised (₹) | empty |
| F | Installment Received (₹) | empty |
| G | Expense Paid (₹) | empty |
| H | Payment Mode | empty |
| I | Invoice / Receipt No. | empty |
| J | Notes | empty |

Auto-filter on A2:J186, freeze at A3. **There is nothing to import from this sheet.** Its column layout is a good fit for a one-row-per-transaction format, and the new system uses it as the template for future Excel imports.

## 4. Issues and ambiguities (need your decision)

| ID | Severity | Issue |
|---|---|---|
| I-1 | **Blocking** | Column C is titled "Opening Balance" but holds several dated amounts per month that are summed as totals. Opening balances are never summed. Most are multiples of ₹99,000 (1×, 2×, 2.5×, 3×, 4×, 5×, 7×), which suggests **installments received** or payments made in units of ₹99,000. What do these amounts represent, who paid them, and to whom? |
| I-2 | **Blocking** | E3:E6 sit under "Monthly Bill" but are labelled by D as Godown Bill, Diesel, Employee and Worker Payment. Are they **expenses paid** in Aug-2025 (₹2,40,000 total), or bills? |
| I-3 | **Blocking** | The monthly bill figures named in the comments (₹10,26,591, ₹9,65,102, ₹6,42,827, plus the extra ₹33,000) are missing from the sheet. Is there an earlier version of the file or the notebook? |
| I-4 | **Blocking** | No rule exists for Cash Balance, Outstanding Bill, Period Shortfall or Status. See the proposed rules in `02-schema-and-accounting-rules.md` §4. They must be confirmed. |
| I-5 | High | B12 is dated **14-12-2026** in the Dec-2025 period. That is a future date. It is probably 14-12-2025. |
| I-6 | High | A20/B20 are stored as plain numbers (46174/46181). As dates they are 01-06-2026 and 08-06-2026. They will be converted as dates with a warning. |
| I-7 | Medium | Periods Nov-2025, Feb-2026, May-2026 and Jul-2026 have no rows. Were there no entries in those months, or are they missing? (Comment E12 says a "Feb+Mar+Apr" 3-month period.) |
| I-8 | Medium | Totals are split by calendar year (2025 / Jan–Sep 2026), not by Indian financial year (Apr–Mar). Which one should reports use? **Proposed: financial year April–March, with calendar-year view also available.** |
| I-9 | Medium | The year-end formulas leave out rows (E24 skips E3:E6; I24/J24 point at row 20, not 23). The new system computes all totals itself and will not copy these formulas. |
| I-10 | Medium | Sindhudurg and Ratnagiri are **locations of A R Trading**, not separate companies. Should the system track a *site/branch* per entry? **Proposed: yes, as an optional "Site" field per company.** |
| I-11 | Info | No Jay Ganesh Transport data exists. That company starts with an empty ledger and an opening balance entered by an admin. |
| I-12 | Info | No party (customer/supplier), payment mode, or invoice/receipt numbers are recorded anywhere. Imported rows will appear in the Pending Work Center as "missing receipt/party". |

## 5. Proposed import mapping (draft, depends on answers to I-1 to I-4)

| Source | Target | Rule |
|---|---|---|
| Sheet `Sindhudurg ` | company = **AR Trading**, site = **Sindhudurg** | From sheet title and company block |
| A (Period) | `financial_period` | Carried down from the last non-empty value; numeric serials converted with a warning |
| B (Date) | `entry_date` | Required. Future dates are blocked until confirmed (I-5) |
| C (amount) | **pending I-1**. Most likely a `receipt` (installment received) | Kept as the original value in `import_rows.raw` |
| D + E rows 3–6 | **pending I-2**. Most likely an `expense` with category = D | |
| C13, C24, E24…M24 | Not imported. Used only as **reconciliation control totals** | System total must equal 16,83,000 and 36,73,500 |
| Comments | `notes` on the related period/import row | Original text kept |
| Sheet `Rataagiri ` | Nothing imported | Empty template |

Every imported row keeps `source_file`, `source_sheet`, `source_row` and a SHA-256 of the file for traceability. Import runs as: **upload → preview → validation report → duplicate report → reconciliation report → explicit confirm → rows created as Draft → accountant posts**.

## 6. Decisions log

| Date | Issue | Decision (by owner) | Effect on import |
|---|---|---|---|
| 2026-10-18 | I-1 | Column C amounts are **money received from a customer** (installments). | Imported as `receipt` entries: Dr Cash/Bank, Cr Accounts Receivable. The customer name is not in the workbook, so each row is flagged "party missing" in the Pending Work Center until a user picks the customer. No party is invented. |
| 2026-10-18 | I-2 | E3:E6 (Godown Bill, Diesel, Employee, Worker) are **expenses paid, by cash or bank**. | Imported as `expense` entries with category = column D. The payment account isn't given per row, so each row is flagged "payment method missing" and posts only after a user picks Cash or Bank. |
| — | I-3, I-4, I-5, I-7, I-8, I-10 | Open | Phase 2 proceeds with the proposed defaults: FY April–March, Site per company, B12 blocked until confirmed. |
