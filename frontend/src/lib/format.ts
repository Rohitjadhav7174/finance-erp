// Indian formatting helpers. Amounts arrive from the API as decimal STRINGS
// (e.g. "125000.00") and are never converted to floating point for arithmetic;
// these helpers only format them for display.

/** Groups an integer digit string the Indian way: 1,25,00,000 */
function groupIndian(intDigits: string): string {
  if (intDigits.length <= 3) return intDigits;
  const last3 = intDigits.slice(-3);
  const rest = intDigits.slice(0, -3);
  return rest.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3;
}

/** "125000.5" -> "₹1,25,000.50"; "-99000" -> "-₹99,000.00". Rounds half away from zero to 2 dp. */
export function formatINR(value: string | number | null | undefined, opts: { symbol?: boolean } = {}): string {
  if (value === null || value === undefined || value === '') return '—';
  const raw = typeof value === 'number' ? value.toFixed(2) : value.trim();
  const m = /^(-)?(\d+)(?:\.(\d+))?$/.exec(raw);
  if (!m) return '—';
  const [, sign, intPart, fracRaw = ''] = m;
  let intDigits = intPart.replace(/^0+(?=\d)/, '');
  let frac = (fracRaw + '000').slice(0, 3);
  // round to 2 decimal places using string arithmetic (no float error)
  let cents = Number(frac.slice(0, 2)) + (Number(frac[2]) >= 5 ? 1 : 0);
  if (cents === 100) {
    cents = 0;
    intDigits = (BigInt(intDigits) + 1n).toString();
  }
  frac = String(cents).padStart(2, '0');
  const isZero = /^0+$/.test(intDigits) && cents === 0;
  const symbol = opts.symbol === false ? '' : '₹';
  return `${sign && !isZero ? '-' : ''}${symbol}${groupIndian(intDigits)}.${frac}`;
}

/** ISO date "2025-08-26" -> "26-08-2025" */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : '—';
}

/** Financial year label for a date, e.g. 2025-08-26 with April start -> "2025-26" */
export function fyLabel(iso: string, startMonth = 4): string {
  const [y, mo] = iso.split('-').map(Number);
  const start = mo >= startMonth ? y : y - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, '0')}`;
}

export const ROLE_LABELS: Record<string, string> = {
  super_admin: 'Super Admin',
  company_admin: 'Company Admin',
  accountant: 'Accountant',
  data_entry: 'Data Entry',
  viewer: 'Viewer',
};
