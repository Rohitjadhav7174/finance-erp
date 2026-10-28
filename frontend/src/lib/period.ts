import { todayISO } from './money';

export type PresetKey = 'this_month' | 'last_month' | 'this_fy' | 'last_fy' | 'custom';

export interface Period { preset: PresetKey; from: string; to: string }

const iso = (y: number, m: number, d: number) => new Date(Date.UTC(y, m, d)).toISOString().slice(0, 10);

export function presetRange(key: Exclude<PresetKey, 'custom'>, fyStartMonth = 4, today = todayISO()): { from: string; to: string } {
  const [y, m] = today.split('-').map(Number);
  const mi = m - 1;
  switch (key) {
    case 'this_month':
      return { from: iso(y, mi, 1), to: today };
    case 'last_month':
      return { from: iso(y, mi - 1, 1), to: iso(y, mi, 0) };
    case 'this_fy': {
      const start = m >= fyStartMonth ? y : y - 1;
      return { from: iso(start, fyStartMonth - 1, 1), to: today };
    }
    case 'last_fy': {
      const start = (m >= fyStartMonth ? y : y - 1) - 1;
      return { from: iso(start, fyStartMonth - 1, 1), to: iso(start + 1, fyStartMonth - 1, 0) };
    }
  }
}

export const PRESETS: { value: PresetKey; label: string }[] = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'this_fy', label: 'This financial year' },
  { value: 'last_fy', label: 'Last financial year' },
  { value: 'custom', label: 'Custom dates' },
];
