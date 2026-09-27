/** 认证 API 服务层 — 登录/注册/身份切换 */

import { API_BASE } from './client';

function jsonHeaders(): Record<string, string> {
  return { 'Content-Type': 'application/json' };
}

async function readResponseBody(response: Response): Promise<Record<string, unknown>> {
  const responseText = await response.text();
  if (!responseText) return {};

  try {
    const parsedBody: unknown = JSON.parse(responseText);
    return parsedBody && typeof parsedBody === 'object'
      ? parsedBody as Record<string, unknown>
      : {};
  } catch {
    // Proxies and application servers may return plain text for a 500 response.
    return { detail: responseText };
  }
}

function getResponseError(body: Record<string, unknown>, fallbackMessage: string): string {
  const detail = body.detail ?? body.message;
  return typeof detail === 'string' && detail.trim() ? detail : fallbackMessage;
}

export interface LoginRequest {
  email: string;
  password: string;
  role: 'patient' | 'doctor' | 'admin';
}

export interface LoginResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in?: number;
  user: {
    id: string;
    email: string;
    role: string;
    name?: string;
  };
}

export interface RegisterRequest {
  email: string;
  password: string;
  role: 'patient' | 'doctor';
  full_name: string;
  phone?: string;
  age_years?: number | null;
  age_months?: number | null;
  gender?: 'male' | 'female' | null;
  province?: string;
  city?: string;
  district?: string;
  street?: string;
  education?: string;
  license_number?: string;
  hospital?: string;
  department?: string;
  title?: string;
  years_of_practice?: number | null;
  specialties?: string;
}

export interface UserInfo {
  id: string;
  email: string;
  role: string;
  name?: string;
  full_name?: string;
}

export async function login(data: LoginRequest): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      username: data.email,
      password: data.password,
    }),
  });
  const json = await readResponseBody(res) as LoginResponse & Record<string, unknown>;
  if (!res.ok) throw new Error(getResponseError(json, 'Login failed'));
  localStorage.setItem('access_token', json.access_token);
  localStorage.setItem('user_role', json.user?.role || data.role);
  return json;
}

export async function register(data: RegisterRequest): Promise<{ message?: string; access_token?: string; user?: { id: string; email: string; role: string } }> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(data),
  });

  const json = await readResponseBody(res) as {
    message?: string;
    detail?: string;
    access_token?: string;
    user?: { id: string; email: string; role: string };
  };
  if (!res.ok) throw new Error(getResponseError(json, 'Register failed'));

  if (json.access_token) {
    localStorage.setItem('access_token', json.access_token);
    localStorage.setItem('user_role', json.user?.role || data.role);
  }
  return json;
}

export async function registerDoctor(data: RegisterRequest, files: File[]): Promise<{ message: string }> {
  const fd = new FormData();
  for (const [k, v] of Object.entries(data)) {
    if (v !== undefined && v !== null && v !== '') fd.append(k, String(v));
  }
  for (const f of files) fd.append('upload_files', f);
  const res = await fetch(`${API_BASE}/auth/register/doctor`, { method: 'POST', body: fd });
  const json = await readResponseBody(res) as { message?: string; detail?: string };
  if (!res.ok) throw new Error(getResponseError(json, '注册失败'));
  return { message: json.message || '注册成功' };
}

export async function getMe(): Promise<UserInfo> {
  const token = localStorage.getItem('access_token');
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  const json = await readResponseBody(res) as UserInfo & Record<string, unknown>;
  if (!res.ok) throw new Error(getResponseError(json, 'Failed to get user info'));
  return json;
}

export async function logout(): Promise<void> {
  const token = localStorage.getItem('access_token');
  if (token) {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => {});
  }
  localStorage.removeItem('access_token');
  localStorage.removeItem('user_role');
  localStorage.removeItem('guest_token');
  localStorage.removeItem('guest_status');
}

export function getToken(): string | null {
  return localStorage.getItem('access_token');
}

export function getUserRole(): string | null {
  return localStorage.getItem('user_role');
}

export function isLoggedIn(): boolean {
  return !!getToken();
}
