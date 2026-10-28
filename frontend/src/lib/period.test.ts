import { presetRange } from './period';

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
