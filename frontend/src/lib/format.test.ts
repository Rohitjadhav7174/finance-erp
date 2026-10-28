import { formatDate, formatINR, fyLabel } from './format';

describe('formatINR', () => {
  it.each([
    ['0', '₹0.00'],
    ['99000', '₹99,000.00'],
    ['125000', '₹1,25,000.00'],
    ['5356500', '₹53,56,500.00'],
    ['1026591.5', '₹10,26,591.50'],
    ['12345678901.23', '₹12,34,56,78,901.23'],
    ['-49500', '-₹49,500.00'],
    ['0.005', '₹0.01'],
    ['999.995', '₹1,000.00'],
    ['-0.001', '₹0.00'],
  ])('%s -> %s', (input, expected) => {
    expect(formatINR(input)).toBe(expected);
  });

  it('handles empty and invalid input', () => {
    expect(formatINR(null)).toBe('—');
    expect(formatINR('')).toBe('—');
    expect(formatINR('12abc')).toBe('—');
  });

  it('can omit the symbol', () => {
    expect(formatINR('125000', { symbol: false })).toBe('1,25,000.00');
  });
});

describe('dates', () => {
  it('formats DD-MM-YYYY', () => {
    expect(formatDate('2025-08-26')).toBe('26-08-2025');
    expect(formatDate(null)).toBe('—');
  });
  it('computes Indian financial year', () => {
    expect(fyLabel('2025-08-26')).toBe('2025-26');
    expect(fyLabel('2026-03-31')).toBe('2025-26');
    expect(fyLabel('2026-04-01')).toBe('2026-27');
  });
});
