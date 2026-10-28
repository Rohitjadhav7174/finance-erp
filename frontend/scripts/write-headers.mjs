// Writes dist/_headers and dist/_redirects for Cloudflare Pages (also understood by Netlify).
// The Content-Security-Policy only allows this site, the API and Supabase Auth — so even if a
// script-injection bug appeared, the browser would refuse to send data anywhere else.
import { writeFileSync } from 'node:fs';

const origin = (u, name) => {
  if (!u) throw new Error(`${name} must be set when building for production`);
  const url = new URL(u);
  if (url.protocol !== 'https:' && url.hostname !== 'localhost') throw new Error(`${name} must use https`);
  return url.origin;
};
const api = origin(process.env.VITE_API_URL, 'VITE_API_URL');
const supabase = origin(process.env.VITE_SUPABASE_URL, 'VITE_SUPABASE_URL');

const csp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'", // Mantine sets some inline styles
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${api} ${supabase}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
  'upgrade-insecure-requests',
].join('; ');

writeFileSync('dist/_headers', `/*
  Content-Security-Policy: ${csp}
  Strict-Transport-Security: max-age=63072000; includeSubDomains
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
  X-Robots-Tag: noindex, nofollow

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/index.html
  Cache-Control: no-cache
`);
writeFileSync('dist/_redirects', '/*  /index.html  200\n'); // single-page app: every route serves the app
console.log(`wrote dist/_headers (api ${api}, auth ${supabase}) and dist/_redirects`);
