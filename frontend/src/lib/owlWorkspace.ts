// Owl workspace client — the organisation layer: projects, folders, where a
// conversation is filed, pinning, archiving, and cross-conversation search.
//
// Chat itself lives in `owlChat.ts`. These are separate jobs against separate
// endpoints, so they stay separate modules.

export interface Project {
  id: string;
  name: string;
  instructions: string;
  position: number;
  archived: boolean;
  created_at: string;
  updated_at: string;
  conversation_count?: number;
}

export interface Folder {
  id: string;
  project_id: string;
  name: string;
  parent_id: string | null;
  position: number;
  conversation_count?: number;
  children?: Folder[];
}

export interface SearchHit {
  conversation_id: string;
  title: string;
  project_id: string | null;
  folder_id: string | null;
  role: 'user' | 'assistant';
  snippet: string;
  ts: string;
}

/** The server states why a request was refused; surface that rather than a
 *  generic failure, since these errors are all actionable by the user. */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init?.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch { /* non-JSON error body — keep the status message */ }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown): RequestInit['body'] => JSON.stringify(body);

// ─── Projects ───────────────────────────────────────────────────────────────

export function listProjects(includeArchived = false): Promise<Project[]> {
  return request(`/api/owl/projects${includeArchived ? '?include_archived=true' : ''}`);
}

export function getProject(id: string): Promise<Project> {
  return request(`/api/owl/projects/${id}`);
}

export function createProject(name: string, instructions = ''): Promise<Project> {
  return request('/api/owl/projects', { method: 'POST', body: json({ name, instructions }) });
}

/** Send only what changed — omitted fields are left alone server-side. */
export function updateProject(
  id: string,
  patch: { name?: string; instructions?: string },
): Promise<Project> {
  return request(`/api/owl/projects/${id}`, { method: 'PATCH', body: json(patch) });
}

export function setProjectArchived(id: string, archived: boolean): Promise<Project> {
  return request(`/api/owl/projects/${id}/archive`, { method: 'POST', body: json({ archived }) });
}

/** Deleting a project unfiles its conversations; it never destroys them. The
 *  returned count is how many were released, which the UI states back. */
export function deleteProject(id: string): Promise<{ conversations_unfiled: number }> {
  return request(`/api/owl/projects/${id}`, { method: 'DELETE' });
}

export function reorderProjects(orderedIds: string[]): Promise<{ ok: boolean }> {
  return request('/api/owl/projects/reorder', {
    method: 'POST',
    body: json({ ordered_ids: orderedIds }),
  });
}

// ─── Folders ────────────────────────────────────────────────────────────────

/** The project's folders, already nested. */
export function listFolders(projectId: string): Promise<Folder[]> {
  return request(`/api/owl/projects/${projectId}/folders`);
}

export function createFolder(
  projectId: string,
  name: string,
  parentId: string | null = null,
): Promise<Folder> {
  return request(`/api/owl/projects/${projectId}/folders`, {
    method: 'POST',
    body: json({ name, parent_id: parentId }),
  });
}

export function renameFolder(id: string, name: string): Promise<Folder> {
  return request(`/api/owl/folders/${id}`, { method: 'PATCH', body: json({ name }) });
}

/** `parentId: null` moves the folder to its project's root. `move` is explicit
 *  so a rename can never be mistaken for a move to the root. */
export function moveFolder(id: string, parentId: string | null): Promise<Folder> {
  return request(`/api/owl/folders/${id}`, {
    method: 'PATCH',
    body: json({ parent_id: parentId, move: true }),
  });
}

/** Deleting a folder lifts its conversations to the project root. */
export function deleteFolder(id: string): Promise<{ conversations_released: number }> {
  return request(`/api/owl/folders/${id}`, { method: 'DELETE' });
}

// ─── Conversation placement ─────────────────────────────────────────────────

/** File a conversation. Both null unfiles it; a folder always needs its project. */
export function moveConversation(
  id: string,
  projectId: string | null,
  folderId: string | null,
): Promise<{ ok: boolean }> {
  return request(`/api/owl/sessions/${id}/placement`, {
    method: 'PATCH',
    body: json({ project_id: projectId, folder_id: folderId }),
  });
}

export function setPinned(id: string, pinned: boolean): Promise<{ ok: boolean }> {
  return request(`/api/owl/sessions/${id}/pin`, { method: 'POST', body: json({ pinned }) });
}

/** Archiving hides a conversation from the default lists and is reversible.
 *  Deletion is not — it destroys the transcript. */
export function setArchived(id: string, archived: boolean): Promise<{ ok: boolean }> {
  return request(`/api/owl/sessions/${id}/archive`, { method: 'POST', body: json({ archived }) });
}

// ─── Search ─────────────────────────────────────────────────────────────────

/** One result per matching message, with a snippet — so a hit points at where
 *  the match is, not merely at the conversation that contained it. */
export function searchMessages(
  query: string,
  opts: { projectId?: string; limit?: number } = {},
): Promise<SearchHit[]> {
  const params = new URLSearchParams({ q: query });
  if (opts.projectId) params.set('project_id', opts.projectId);
  if (opts.limit) params.set('limit', String(opts.limit));
  return request(`/api/owl/search?${params}`);
}
