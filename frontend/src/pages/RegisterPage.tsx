import { SegmentedControl, Stack } from '@mantine/core';
import { useState } from 'react';
import { ReportViewPage } from './ReportsPage';

/** The Excel-style register: the monthly balance sheet, or every transaction line by line. */
export function RegisterPage() {
  const [view, setView] = useState('monthly_balance_sheet');
  return (
    <Stack>
      <SegmentedControl value={view} onChange={setView}
        data={[{ value: 'monthly_balance_sheet', label: 'Monthly sheet' }, { value: 'transaction_register', label: 'All transactions' }]} />
      <ReportViewPage key={view} fixedName={view} />
    </Stack>
  );
}
