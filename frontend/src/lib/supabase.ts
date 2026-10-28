import { createClient } from '@supabase/supabase-js';

// Supabase is used ONLY for sign-in. The anon key is public by design; it cannot
// reach finance data (the `fin` schema is not exposed and grants nothing to anon/authenticated).
const url = import.meta.env.VITE_SUPABASE_URL as string;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  // eslint-disable-next-line no-console
  console.error('VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set. Copy .env.example to .env.local.');
}

export const supabase = createClient(url ?? 'http://invalid.local', anonKey ?? 'missing', {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
