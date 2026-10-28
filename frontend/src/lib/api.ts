import { supabase } from './supabase';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '';

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

/** Fetch wrapper: attaches the current access token, parses JSON, normalises errors. */
export async function api<T>(path: string, init: RequestInit & { idempotencyKey?: string } = {}): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (init.idempotencyKey) headers.set('Idempotency-Key', init.idempotencyKey);

  let res: Response;
  try {
    res = await fetch(`${API_URL}/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your internet connection and try again.');
  }
  if (res.status === 401) {
    await supabase.auth.signOut();
    throw new ApiError(401, 'Your session has expired. Please sign in again.');
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    let message = 'Something went wrong. Please try again.';
    if (typeof body?.detail === 'string') message = body.detail;
    else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join('; ');
    else if (res.status === 429) message = 'Too many requests. Please wait a minute and try again.';
    throw new ApiError(res.status, message, body?.code);
  }
  return body as T;
}

export const json = (data: unknown) => JSON.stringify(data);

/** Downloads a file from the API (with the user's token) and saves it. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const { data } = await supabase.auth.getSession();
  const res = await fetch(`${API_URL}/api${path}`, {
    headers: data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {},
  });
  if (!res.ok) {
    let message = 'Download failed. Please try again.';
    try { message = (await res.json()).detail ?? message; } catch { /* not JSON */ }
    throw new ApiError(res.status, message);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
