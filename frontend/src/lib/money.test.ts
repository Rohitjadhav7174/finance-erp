import { addMonths, autoAllocate, cleanAmount, fromPaise, isAmount, splitEqually, sumAmounts, toPaise } from './money';

describe('money', () => {
  it('parses and formats paise exactly', () => {
    expect(toPaise('0.1') + toPaise('0.2')).toBe(toPaise('0.3'));
    expect(fromPaise(toPaise('1,25,000.5'))).toBe('125000.50');
    expect(sumAmounts(['49500', '49500.00', null])).toBe('99000.00');
  });

  it('validates amounts', () => {
    expect(isAmount('99000')).toBe(true);
    expect(isAmount('99000.55')).toBe(true);
    expect(isAmount('0')).toBe(false);
    expect(isAmount('1.234')).toBe(false);
    expect(isAmount('-5')).toBe(false);
    expect(cleanAmount('₹ 1,25,000')).toBe('125000');
  });

  it('splits installments without losing a paisa', () => {
    expect(splitEqually('100000', 3)).toEqual(['33333.33', '33333.33', '33333.34']);
    expect(sumAmounts(splitEqually('1026591', 7))).toBe('1026591.00');
  });

  it('adds months with month-end clamping', () => {
    expect(addMonths('2026-01-31', 1)).toBe('2026-02-28');
    expect(addMonths('2025-11-15', 3)).toBe('2026-02-15');
  });

  it('auto-allocates oldest first', () => {
    const bills = [{ id: 'a', outstanding: '49500' }, { id: 'b', outstanding: '99000' }];
    expect(autoAllocate('60000', bills)).toEqual({ a: '49500.00', b: '10500.00' });
    expect(autoAllocate('10', bills)).toEqual({ a: '10.00' });
  });
});
