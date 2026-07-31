import { describe, expect, it, vi } from 'vitest';
import worker from '../src/index';

function envWithStub() {
  const stub = {
    fetch: vi.fn(async (request: Request) => {
      const body = await request.json();
      return Response.json(body);
    }),
  };
  const namespace = {
    idFromName: vi.fn((name: string) => name),
    get: vi.fn(() => stub),
  };
  return {
    env: {
      ADMIN_TOKEN: 'admin-secret',
      ESP_ANYWHERE_INSTALLATION: namespace,
    },
  };
}

describe('Worker HTTP routing', () => {
  it('forwards an intact activation request body to the Durable Object', async () => {
    const { env } = envWithStub();
    const request = new Request('http://worker/admin/activation-code', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer admin-secret',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        installation_id: 'first-real-test',
        role: 'home_assistant',
      }),
    });

    const response = await worker.fetch(request, env as any, {} as any);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      installation_id: 'first-real-test',
      role: 'home_assistant',
    });
  });

  it('forwards an intact claim request body to the Durable Object', async () => {
    const { env } = envWithStub();
    const request = new Request('http://worker/claim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: 'first-real-test:0123456789abcdef01234567',
        device_id: 'esp32_c3_001',
      }),
    });

    const response = await worker.fetch(request, env as any, {} as any);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      code: 'first-real-test:0123456789abcdef01234567',
      device_id: 'esp32_c3_001',
    });
  });
});
