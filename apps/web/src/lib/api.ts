// API client — all requests go through here
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

function getToken(): string | null {
  return localStorage.getItem('dl_token');
}

export function setToken(token: string): void {
  localStorage.setItem('dl_token', token);
}

export function clearToken(): void {
  localStorage.removeItem('dl_token');
  localStorage.removeItem('dl_workspace');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      msg = body.error || body.detail || msg;
    } catch {}
    throw new Error(msg);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

// ── Auth ───────────────────────────────────────────────────────────────────────

export const auth = {
  register: (email: string, display_name: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>('/auth/register', {
      method: 'POST', body: JSON.stringify({ email, display_name, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string; refresh_token: string }>('/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    }),
  me: () => request<{ id: string; email: string; display_name: string }>('/auth/me'),
};

// ── Workspaces ────────────────────────────────────────────────────────────────

export type Workspace = { id: string; name: string; slug: string; description?: string; created_at: string };

export const workspaces = {
  list: () => request<Workspace[]>('/workspaces'),
  get: (id: string) => request<Workspace>(`/workspaces/${id}`),
  create: (name: string, description?: string) =>
    request<Workspace>('/workspaces', { method: 'POST', body: JSON.stringify({ name, description }) }),
};

// ── Datasets ──────────────────────────────────────────────────────────────────

export type Dataset = {
  id: string; workspace_id: string; name: string; description?: string;
  source_type: string; original_filename?: string; row_count: number;
  import_status: string; is_sample: boolean; created_at: string; updated_at: string;
};

export const datasets = {
  list: (wsId: string) => request<Dataset[]>(`/workspaces/${wsId}/datasets`),
  create: (wsId: string, name: string, description?: string) =>
    request<Dataset>(`/workspaces/${wsId}/datasets`, { method: 'POST', body: JSON.stringify({ name, description }) }),
  get: (wsId: string, dsId: string) => request<Dataset>(`/workspaces/${wsId}/datasets/${dsId}`),
  delete: (wsId: string, dsId: string) =>
    request<void>(`/workspaces/${wsId}/datasets/${dsId}`, { method: 'DELETE' }),
  upload: async (wsId: string, dsId: string, file: File) => {
    const token = getToken();
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/workspaces/${wsId}/datasets/${dsId}/upload`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!res.ok) { const b = await res.json(); throw new Error(b.error || 'Upload failed'); }
    return res.json();
  },
  importRows: (wsId: string, dsId: string, mapping: Record<string, string>) =>
    request<{ id: string; status: string }>(`/workspaces/${wsId}/datasets/${dsId}/import`, {
      method: 'POST', body: JSON.stringify({ mapping }),
    }),
  preview: (wsId: string, dsId: string, page = 1) =>
    request<{ total: number; rows: { row_number: number; data: Record<string, unknown> }[] }>(
      `/workspaces/${wsId}/datasets/${dsId}/preview?page=${page}`
    ),
};

// ── Reconciliation ─────────────────────────────────────────────────────────────

export type ReconJob = {
  id: string; name: string; status: string; matched_count: number;
  unmatched_count: number; discrepancy_count: number; total_processed: number;
  dataset_a_id: string; dataset_b_id: string; created_at: string;
};

export const reconciliation = {
  list: (wsId: string) => request<ReconJob[]>(`/workspaces/${wsId}/reconciliation/jobs`),
  create: (wsId: string, payload: Record<string, unknown>) =>
    request<ReconJob>(`/workspaces/${wsId}/reconciliation/jobs`, { method: 'POST', body: JSON.stringify(payload) }),
  get: (wsId: string, jobId: string) => request<ReconJob>(`/workspaces/${wsId}/reconciliation/jobs/${jobId}`),
  run: (wsId: string, jobId: string) =>
    request<ReconJob>(`/workspaces/${wsId}/reconciliation/jobs/${jobId}/run`, { method: 'POST' }),
  results: (wsId: string, jobId: string, page = 1, category?: string) =>
    request<{ results: unknown[]; summary: Record<string, number>; total: number }>(
      `/workspaces/${wsId}/reconciliation/jobs/${jobId}/results?page=${page}${category ? `&category=${category}` : ''}`
    ),
  export: (wsId: string, jobId: string, format = 'csv', filter?: string) => {
    const token = getToken();
    const url = `${API_BASE}/workspaces/${wsId}/reconciliation/jobs/${jobId}/export?format=${format}${filter ? `&filter=${filter}` : ''}`;
    const a = document.createElement('a');
    a.href = url;
    // Can't set Authorization in anchor tag — open in new tab
    window.open(url, '_blank');
  },
};

// ── Discrepancies ─────────────────────────────────────────────────────────────

export const discrepancies = {
  list: (wsId: string, params?: { category?: string; status?: string; job_id?: string; page?: number }) => {
    const q = new URLSearchParams();
    if (params?.category) q.set('category', params.category);
    if (params?.status) q.set('status', params.status);
    if (params?.job_id) q.set('job_id', params.job_id);
    if (params?.page) q.set('page', String(params.page));
    return request<{ items: unknown[]; total: number; pages: number }>(`/workspaces/${wsId}/discrepancies?${q}`);
  },
  review: (wsId: string, discId: string, action: string, notes?: string) =>
    request<unknown>(`/workspaces/${wsId}/discrepancies/${discId}/review`, {
      method: 'POST', body: JSON.stringify({ action, notes }),
    }),
};

// ── Dashboard ─────────────────────────────────────────────────────────────────

export const dashboard = {
  get: (wsId: string) => request<Record<string, unknown>>(`/workspaces/${wsId}/dashboard`),
};
