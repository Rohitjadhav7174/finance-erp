import { Group, Select } from '@mantine/core';
import { useCompany } from '../context/CompanyContext';
import { PRESETS, presetRange, type Period, type PresetKey } from '../lib/period';
import { DateField } from './fields';

export function usePeriodDefaults(preset: Exclude<PresetKey, 'custom'> = 'this_fy'): Period {
  const { company } = useCompany();
  return { preset, ...presetRange(preset, company?.fy_start_month ?? 4) };
}

export function PeriodPicker({ value, onChange, presets = PRESETS }: {
  value: Period; onChange: (p: Period) => void; presets?: typeof PRESETS;
}) {
  const { company } = useCompany();
  return (
    <Group gap="xs" align="flex-end" wrap="wrap">
      <Select aria-label="Period" size="sm" w={190} allowDeselect={false} value={value.preset} data={presets}
        onChange={(k) => {
          if (!k) return;
          if (k === 'custom') onChange({ ...value, preset: 'custom' });
          else onChange({ preset: k as PresetKey, ...presetRange(k as Exclude<PresetKey, 'custom'>, company?.fy_start_month ?? 4) });
        }} />
      {value.preset === 'custom' && (
        <>
          <DateField size="sm" aria-label="From date" value={value.from} onChange={(e) => onChange({ ...value, from: e.currentTarget.value })} />
          <DateField size="sm" aria-label="To date" value={value.to} onChange={(e) => onChange({ ...value, to: e.currentTarget.value })} />
        </>
      )}
    </Group>
  );
}
