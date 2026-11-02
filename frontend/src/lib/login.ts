// Staff can sign in with a plain login ID (e.g. "Ramdas"). Supabase needs an email, so an ID without "@"
// becomes ramdas@login.local — an internal address that never receives mail.
export const LOGIN_DOMAIN = 'login.local';
export const loginEmail = (id: string) => {
  const v = id.trim().toLowerCase();
  return v.includes('@') ? v : `${v}@${LOGIN_DOMAIN}`;
};
