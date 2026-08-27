// The session, resolved once.
//
// Both layouts and the Owl workspace each carried their own copy of the same
// auth bootstrap — fetch status, redirect if unauthenticated, paint the user
// block, wire logout and the sandbox toggle. Three copies drifted: only one of
// them checked per-agent access, and only one showed the admin chip. This is
// that logic, owned in one place.

export interface SessionUser {
  authed: boolean;
  username?: string;
  name?: string;
  role?: string;
  /** 'admin' | 'user' — governs the admin link and the sandbox toggle. */
  access?: string;
  /** Agent slugs this user may reach. */
  agents?: string[];
}

const SIGN_IN = '/';

/**
 * The status request, in flight or resolved, shared by every caller.
 *
 * A shell and its page both boot: `bootShell()` paints the user block, and a page
 * may want the name for itself. Each called `requireSession()` and each fetched
 * `/api/auth/status`, so every screen paid two identical round trips and the
 * slower one decided when the page could finish painting. The session cannot
 * change without a navigation, so one promise serves all of them.
 */
let inFlight: Promise<SessionUser | null> | null = null;

/**
 * Resolve the session, or leave for the sign-in page.
 *
 * Returns `null` when the caller should stop — navigation is already under way,
 * so every caller's next line must be `return`.
 */
export async function requireSession(): Promise<SessionUser | null> {
  inFlight ??= fetchSession();
  return inFlight;
}

async function fetchSession(): Promise<SessionUser | null> {
  try {
    const res = await fetch('/api/auth/status');
    const user: SessionUser = await res.json();
    if (!user.authed) {
      window.location.href = SIGN_IN;
      return null;
    }
    return user;
  } catch {
    // A failed status call is indistinguishable from being signed out, and
    // guessing "signed in" would render a shell over nothing.
    window.location.href = SIGN_IN;
    return null;
  }
}

/** Whether the admin sandbox is currently on. Never throws; false when unknown. */
export async function sandboxActive(): Promise<boolean> {
  try {
    const res = await fetch('/api/admin/sandbox/status');
    if (!res.ok) return false;
    return Boolean((await res.json()).sandbox);
  } catch {
    return false;
  }
}

/** Whether this user may reach an agent, by its slug. */
export function canReach(user: SessionUser, slug: string): boolean {
  return (user.agents ?? []).includes(slug);
}

export function displayName(user: SessionUser): string {
  return user.name || user.username || '';
}

export function initial(user: SessionUser): string {
  return (displayName(user).trim()[0] || '·').toUpperCase();
}

export function isAdmin(user: SessionUser): boolean {
  return user.access === 'admin';
}

/**
 * Paint the user block a shell has already laid out. Elements are looked up by
 * id so a layout only has to provide the slots, not the logic.
 */
export function paintUser(
  user: SessionUser,
  ids: { avatar?: string; name?: string; role?: string } = {},
): void {
  const { avatar = 'user-avatar', name = 'user-name', role = 'user-role' } = ids;

  const avatarEl = document.getElementById(avatar);
  if (avatarEl) avatarEl.textContent = initial(user);

  const nameEl = document.getElementById(name);
  if (nameEl) nameEl.textContent = displayName(user);

  const roleEl = document.getElementById(role);
  if (roleEl) roleEl.textContent = user.role || (isAdmin(user) ? 'Admin' : '');
}

export function wireLogout(id = 'logout-btn'): void {
  document.getElementById(id)?.addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    window.location.href = SIGN_IN;
  });
}

/**
 * The admin sandbox toggle. Revealed only for admins, and labelled with the
 * state it is *in* rather than the action — a toggle that lies about its state
 * is worse than no toggle. The label uses the drift mark when active, because
 * sandbox is a condition the system is in.
 */
export function wireSandboxToggle(user: SessionUser, active: boolean, id = 'sandbox-toggle'): void {
  const button = document.getElementById(id);
  if (!button || !isAdmin(user)) return;

  button.hidden = false;
  const paint = (on: boolean) => {
    button.textContent = on ? 'sandbox on' : 'sandbox off';
    button.className = on ? 'ds-mark ds-mark--drift' : 'ds-mark ds-mark--idle';
  };
  paint(active);

  button.addEventListener('click', async () => {
    const endpoint = active ? '/api/admin/sandbox/disable' : '/api/admin/sandbox/enable';
    await fetch(endpoint, { method: 'POST' });
    window.location.reload();
  });
}

/** Today, in the readout format the chrome uses. */
export function todayLabel(date = new Date()): string {
  const day = String(date.getDate()).padStart(2, '0');
  const month = date.toLocaleString('en-GB', { month: 'short' }).toUpperCase();
  return `${day} ${month} ${date.getFullYear()}`;
}

/**
 * The whole boot sequence for a shell: resolve the session, paint the user,
 * wire logout and the sandbox toggle, reveal the admin link.
 * Returns the user, or null when the caller should stop.
 */
export async function bootShell(options: { adminLinkId?: string } = {}): Promise<SessionUser | null> {
  const user = await requireSession();
  if (!user) return null;

  const sandbox = isAdmin(user) ? await sandboxActive() : false;

  paintUser(user);
  wireLogout();
  wireSandboxToggle(user, sandbox);

  if (isAdmin(user) && options.adminLinkId) {
    const link = document.getElementById(options.adminLinkId);
    if (link) link.hidden = false;
  }

  return user;
}
