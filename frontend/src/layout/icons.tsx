// Small inline icons (avoids a 70 MB icon package). 24px stroke icons.
import type { SVGProps } from 'react';

type P = SVGProps<SVGSVGElement> & { size?: number };

const base = ({ size = 22, ...rest }: P) => ({
  width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
  strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true, ...rest,
});

export const IconHome = (p: P) => (<svg {...base(p)}><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>);
export const IconList = (p: P) => (<svg {...base(p)}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>);
export const IconPlus = (p: P) => (<svg {...base(p)}><path d="M12 5v14M5 12h14" /></svg>);
export const IconClock = (p: P) => (<svg {...base(p)}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>);
export const IconMenu = (p: P) => (<svg {...base(p)}><path d="M4 6h16M4 12h16M4 18h16" /></svg>);
export const IconUsers = (p: P) => (<svg {...base(p)}><circle cx="9" cy="8" r="4" /><path d="M2 21v-1a6 6 0 0112 0v1M16 3.5a4 4 0 010 9M22 21v-1a6 6 0 00-4-5.6" /></svg>);
export const IconBuilding = (p: P) => (<svg {...base(p)}><path d="M3 21h18M5 21V5l7-3v19M19 21V9l-7-3M9 9h.01M9 13h.01M9 17h.01" /></svg>);
export const IconReceipt = (p: P) => (<svg {...base(p)}><path d="M5 3v18l3-2 2 2 2-2 2 2 2-2 3 2V3l-3 2-2-2-2 2-2-2-2 2z" /><path d="M9 9h6M9 13h6" /></svg>);
export const IconArrowDown = (p: P) => (<svg {...base(p)}><path d="M12 5v14M6 13l6 6 6-6" /></svg>);
export const IconArrowUp = (p: P) => (<svg {...base(p)}><path d="M12 19V5M6 11l6-6 6 6" /></svg>);
export const IconSwap = (p: P) => (<svg {...base(p)}><path d="M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7" /></svg>);
export const IconLogout = (p: P) => (<svg {...base(p)}><path d="M15 4h4v16h-4M10 17l5-5-5-5M15 12H3" /></svg>);
export const IconChevron = (p: P) => (<svg {...base(p)}><path d="M6 9l6 6 6-6" /></svg>);
export const IconSearch = (p: P) => (<svg {...base(p)}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>);
export const IconChart = (p: P) => (<svg {...base(p)}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>);
