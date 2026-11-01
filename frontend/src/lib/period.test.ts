import { presetRange, periodLabel } from './period';

describe('period presets (Indian FY starts in April)', () => {
  it('this month and last month', () => {
    expect(presetRange('this_month', 4, '2026-10-18')).toEqual({ from: '2026-10-01', to: '2026-10-18' });
    expect(presetRange('last_month', 4, '2026-01-10')).toEqual({ from: '2025-12-01', to: '2025-12-31' });
  });
  it('financial years', () => {
    expect(presetRange('this_fy', 4, '2026-10-18')).toEqual({ from: '2026-04-01', to: '2026-10-18' });
    expect(presetRange('this_fy', 4, '2026-02-15')).toEqual({ from: '2025-04-01', to: '2026-02-15' });
    expect(presetRange('last_fy', 4, '2026-10-18')).toEqual({ from: '2025-04-01', to: '2026-03-31' });
  });
});

describe('periodLabel', () => {
  it('names one month, a span in one year, and a span across years', () => {
    expect(periodLabel('2026-05-01', '2026-05-31')).toBe('May 2026');
    expect(periodLabel('2026-05-01', '2026-06-30')).toBe('May – June 2026');
    expect(periodLabel('2025-12-01', '2026-01-31')).toBe('December 2025 – January 2026');
  });
});
