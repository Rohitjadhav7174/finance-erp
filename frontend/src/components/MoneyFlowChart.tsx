import { Box, Group, SegmentedControl, Table, Text } from '@mantine/core';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatINR } from '../lib/format';

// Categorical slots 1 & 2 of the reference palette (validated: CVD ΔE 24.7, contrast ≥ 3:1).
const IN = '#2a78d6';
const OUT = '#eb6834';

export interface MonthPoint { month: string; money_in: string; money_out: string; income: string; expenses: string }

const monthLabel = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { month: 'short' });
const compact = (n: number) =>
  n >= 1e7 ? `${(n / 1e7).toFixed(1)}Cr` : n >= 1e5 ? `${(n / 1e5).toFixed(1)}L` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey: string; value: number }[]; label?: string }) {
  if (!active || !payload?.length || !label) return null;
  return (
    <Box p="xs" bg="var(--mantine-color-body)" style={{ border: '1px solid var(--mantine-color-default-border)', borderRadius: 6 }}>
      <Text size="xs" fw={700}>{new Date(label + 'T00:00:00').toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })}</Text>
      {payload.map((p) => (
        <Group key={p.dataKey} gap={6} wrap="nowrap">
          <Box w={10} h={10} style={{ borderRadius: 2, background: p.dataKey === 'in' ? IN : OUT }} />
          <Text size="xs">{p.dataKey === 'in' ? 'Money in' : 'Money out'}: {formatINR(p.value.toFixed(2))}</Text>
        </Group>
      ))}
    </Box>
  );
}

/** Money in vs money out per month (cash movement only — not income/expense). */
export function MoneyFlowChart({ data }: { data: MonthPoint[] }) {
  const [view, setView] = useState('chart');
  const rows = data.map((d) => ({ month: d.month, in: Number(d.money_in), out: Number(d.money_out), raw: d }));
  return (
    <Box>
      <Group justify="space-between" mb="xs" wrap="wrap" gap="xs">
        <Group gap="md">
          <Group gap={6}><Box w={12} h={12} style={{ borderRadius: 3, background: IN }} /><Text size="xs">Money in</Text></Group>
          <Group gap={6}><Box w={12} h={12} style={{ borderRadius: 3, background: OUT }} /><Text size="xs">Money out</Text></Group>
        </Group>
        <SegmentedControl size="xs" value={view} onChange={setView} data={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} />
      </Group>
      {view === 'chart' ? (
        <Box h={220} role="img" aria-label="Bar chart of money in and money out for the last 12 months; switch to Table for exact figures.">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} barGap={2} barCategoryGap="20%" margin={{ top: 4, right: 4, left: -8, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--mantine-color-gray-2)" />
              <XAxis dataKey="month" tickFormatter={monthLabel} tick={{ fontSize: 11, fill: 'var(--mantine-color-dimmed)' }}
                axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tickFormatter={compact} tick={{ fontSize: 11, fill: 'var(--mantine-color-dimmed)' }} axisLine={false}
                tickLine={false} width={44} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: 'var(--mantine-color-gray-1)' }} />
              <Bar dataKey="in" fill={IN} radius={[4, 4, 0, 0]} maxBarSize={18} />
              <Bar dataKey="out" fill={OUT} radius={[4, 4, 0, 0]} maxBarSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </Box>
      ) : (
        <Table.ScrollContainer minWidth={320}>
          <Table fz="xs" striped>
            <Table.Thead><Table.Tr><Table.Th>Month</Table.Th><Table.Th ta="right">Money in</Table.Th><Table.Th ta="right">Money out</Table.Th><Table.Th ta="right">Income</Table.Th><Table.Th ta="right">Expenses</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {data.map((d) => (
                <Table.Tr key={d.month}>
                  <Table.Td>{new Date(d.month + 'T00:00:00').toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}</Table.Td>
                  <Table.Td ta="right">{formatINR(d.money_in, { symbol: false })}</Table.Td>
                  <Table.Td ta="right">{formatINR(d.money_out, { symbol: false })}</Table.Td>
                  <Table.Td ta="right">{formatINR(d.income, { symbol: false })}</Table.Td>
                  <Table.Td ta="right">{formatINR(d.expenses, { symbol: false })}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Box>
  );
}
