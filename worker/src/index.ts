import { InstallationDO } from './DurableObject';
import provisionHtml from './provision-v3.html';
import firmwareImage from './firmware-9477ef.bin';

const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9_-]{2,63}$/;
const ACTIVATION_CODE_PATTERN = /^([a-z0-9][a-z0-9_-]{2,63}):[0-9a-f]{24}$/;

export interface Env {
  ESP_ANYWHERE_INSTALLATION: DurableObjectNamespace;
  ADMIN_TOKEN?: string;
}

export { InstallationDO };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === 'GET' && url.pathname === '/provision') {
      return new Response(provisionHtml, { headers: {
        'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=300',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; connect-src 'self' https://unpkg.com; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
        'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
      } });
    }
    if (request.method === 'GET' && url.pathname === '/provision/manifest.json') {
      return Response.json({ name: 'ESP Anywhere', version: '0.3.0-beta.1',
        builds: [{ chipFamily: 'ESP32-C3', parts: [{ path: '/provision/firmware.bin', offset: 0 }] }],
        new_install_prompt_erase: true }, { headers: { 'Cache-Control': 'public, max-age=300' } });
    }
    if (request.method === 'GET' && url.pathname === '/provision/firmware.bin') {
      return new Response(firmwareImage, { headers: { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'public, max-age=31536000, immutable', 'X-Content-Type-Options': 'nosniff' } });
    }

    // HTTP API: Create Activation Code (Admin only)
    if (request.method === 'POST' && url.pathname === '/admin/activation-code') {
      const authHeader = request.headers.get('Authorization');
      if (!env.ADMIN_TOKEN || authHeader !== `Bearer ${env.ADMIN_TOKEN}`) {
        return new Response('Unauthorized', { status: 401 });
      }
      try {
        const body = (await request.clone().json()) as any;
        const installationId = body.installation_id;
        const role = body.role; // 'home_assistant' or 'device'
        const deviceId = body.device_id;

        if (
          typeof installationId !== 'string'
          || !IDENTIFIER_PATTERN.test(installationId)
          || (role !== 'home_assistant' && role !== 'device')
          || (role === 'device' && (typeof deviceId !== 'string' || !IDENTIFIER_PATTERN.test(deviceId)))
          || (role === 'home_assistant' && deviceId !== undefined && deviceId !== '')
        ) {
          return new Response('Invalid request', { status: 400 });
        }

        const id = env.ESP_ANYWHERE_INSTALLATION.idFromName(installationId);
        const stub = env.ESP_ANYWHERE_INSTALLATION.get(id);

        // Pass request to DO
        return stub.fetch(request);
      } catch (e) {
        return new Response('Bad request', { status: 400 });
      }
    }

    // HTTP API: Claim Code (HA or Device)
    if (request.method === 'POST' && url.pathname === '/claim') {
      try {
        const body = (await request.clone().json()) as any;
        const code = body.code;
        const codeMatch = typeof code === 'string'
          ? ACTIVATION_CODE_PATTERN.exec(code)
          : null;
        if (!codeMatch) {
          return new Response('Invalid code format', { status: 400 });
        }

        const installationId = codeMatch[1];
        const id = env.ESP_ANYWHERE_INSTALLATION.idFromName(installationId);
        const stub = env.ESP_ANYWHERE_INSTALLATION.get(id);

        return stub.fetch(request);
      } catch (e) {
        return new Response('Bad request', { status: 400 });
      }
    }

    if (request.method === 'POST' && url.pathname === '/ha/device-activation-code') {
      try {
        const body = (await request.clone().json()) as any;
        const installationId = body.installation_id;
        const deviceId = body.device_id;
        const authHeader = request.headers.get('Authorization');
        if (typeof installationId !== 'string' || !IDENTIFIER_PATTERN.test(installationId)
          || typeof deviceId !== 'string' || !IDENTIFIER_PATTERN.test(deviceId)
          || !authHeader?.startsWith('Bearer ')) return new Response('Invalid request', { status: 400 });
        const id = env.ESP_ANYWHERE_INSTALLATION.idFromName(installationId);
        return env.ESP_ANYWHERE_INSTALLATION.get(id).fetch(request);
      } catch {
        return new Response('Bad request', { status: 400 });
      }
    }

    // WebSocket Connection
    if (url.pathname === '/ws') {
      const upgradeHeader = request.headers.get('Upgrade');
      if (!upgradeHeader || upgradeHeader !== 'websocket') {
        return new Response('Expected Upgrade: websocket', { status: 426 });
      }

      const installationId = url.searchParams.get('installation_id');
      const role = url.searchParams.get('role'); // "device" or "home_assistant"

      const authHeader = request.headers.get('Authorization');
      const token = authHeader?.startsWith('Bearer ')
        ? authHeader.slice(7)
        : null;

      if (!installationId || !IDENTIFIER_PATTERN.test(installationId) || !role || !token) {
        return new Response('Missing parameters', { status: 400 });
      }

      if (role !== 'device' && role !== 'home_assistant') {
        return new Response('Invalid role', { status: 400 });
      }

      const id = env.ESP_ANYWHERE_INSTALLATION.idFromName(installationId);
      const stub = env.ESP_ANYWHERE_INSTALLATION.get(id);

      return stub.fetch(request);
    }

    return new Response('Not found', { status: 404 });
  },
};
