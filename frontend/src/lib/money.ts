// Exact money arithmetic in the browser using integer paise (BigInt).
// Used only for previews (totals, remaining, equal installment split);
// the server recalculates and validates everything.

export const AMOUNT_RE = /^\d{1,12}(\.\d{1,2})?$/;

export function isAmount(v: string): boolean {
  return AMOUNT_RE.test(v.trim()) && toPaise(v) > 0n;
}

/** Normalises user input like "1,25,000.5" or "₹ 99000" to "125000.5". */
export function cleanAmount(v: string): string {
  return v.replace(/[₹,\s]/g, '');
}

export function toPaise(v: string | null | undefined): bigint {
  const s = cleanAmount(v ?? '');
  const m = /^(\d+)(?:\.(\d{1,2}))?$/.exec(s);
  if (!m) return 0n;
  return BigInt(m[1]) * 100n + BigInt((m[2] ?? '').padEnd(2, '0') || '0');
}

export function fromPaise(p: bigint): string {
  const neg = p < 0n;
  const a = neg ? -p : p;
  return `${neg ? '-' : ''}${a / 100n}.${(a % 100n).toString().padStart(2, '0')}`;
}

export const sumAmounts = (vals: (string | null | undefined)[]) => fromPaise(vals.reduce((t, v) => t + toPaise(v), 0n));

/** Splits a total into n installments; any leftover paise go to the last one. */
export function splitEqually(total: string, n: number): string[] {
  const p = toPaise(total);
  if (n < 1 || p <= 0n) return [];
  const each = p / BigInt(n);
  return Array.from({ length: n }, (_, i) => fromPaise(i === n - 1 ? p - each * BigInt(n - 1) : each));
}

/** Adds whole months to an ISO date, clamping to the month end (31 Jan + 1 month -> 28/29 Feb). */
export function addMonths(iso: string, months: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  const target = new Date(Date.UTC(y, m - 1 + months, 1));
  const last = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(d, last));
  return target.toISOString().slice(0, 10);
}

export const todayISO = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

/** Allocates an amount to bills oldest-first; returns {billId: amount}. */
export function autoAllocate(amount: string, bills: { id: string; outstanding: string }[]): Record<string, string> {
  let left = toPaise(amount);
  const out: Record<string, string> = {};
  for (const b of bills) {
    if (left <= 0n) break;
    const take = toPaise(b.outstanding) < left ? toPaise(b.outstanding) : left;
    if (take > 0n) {
      out[b.id] = fromPaise(take);
      left -= take;
    }
  }
  return out;
}
