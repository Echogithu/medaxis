import assert from 'node:assert/strict';
import { test } from 'node:test';
import { acknowledgeReminder, listReminders } from '../src/api/patient.ts';

globalThis.localStorage = { getItem: () => null };

test('reminder list uses bounded cursor pagination and includes all statuses by default', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl;
  globalThis.fetch = async url => {
    requestedUrl = String(url);
    return Response.json({ items: [], next_cursor: null });
  };

  try {
    await listReminders({ limit: 50 });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const url = new URL(requestedUrl, 'http://localhost');
  assert.equal(url.pathname, '/api/v1/patient/reminders');
  assert.equal(url.searchParams.get('limit'), '50');
  assert.equal(url.searchParams.has('status'), false);
});

test('reminder list sends the server cursor for the next page', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl;
  globalThis.fetch = async url => {
    requestedUrl = String(url);
    return Response.json({ items: [], next_cursor: null });
  };

  try {
    await listReminders({
      limit: 50,
      cursor: { scheduled_at: '2026-09-27T09:00:00+00:00', id: '00000000-0000-4000-8000-000000000001' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  const url = new URL(requestedUrl, 'http://localhost');
  assert.equal(url.searchParams.get('cursor_at'), '2026-09-27T09:00:00+00:00');
  assert.equal(url.searchParams.get('cursor_id'), '00000000-0000-4000-8000-000000000001');
});

test('reminder acknowledgement uses PATCH acknowledge route and returns server state', async () => {
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url: String(url), options };
    return Response.json({
      id: 'reminder-1', status: 'acknowledged', acknowledged_at: '2026-09-27T09:00:00+00:00',
    });
  };

  try {
    const result = await acknowledgeReminder('reminder-1');
    assert.equal(result.status, 'acknowledged');
    assert.equal(result.acknowledged_at, '2026-09-27T09:00:00+00:00');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(request.url, '/api/v1/patient/reminders/reminder-1/acknowledge');
  assert.equal(request.options.method, 'PATCH');
});

test('failed reminder acknowledgement remains an error', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response('', { status: 409 });

  try {
    await assert.rejects(acknowledgeReminder('reminder-1'), /acknowledge/i);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
