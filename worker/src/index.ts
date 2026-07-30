import { InstallationDO } from './DurableObject';

export interface Env {
  ESP_ANYWHERE_INSTALLATION: DurableObjectNamespace;
  ADMIN_TOKEN?: string;
}

export { InstallationDO };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // HTTP API: Create Activation Code (Admin only)
    if (request.method === 'POST' && url.pathname === '/admin/activation-code') {
      const authHeader = request.headers.get('Authorization');
      if (!env.ADMIN_TOKEN || authHeader !== `Bearer ${env.ADMIN_TOKEN}`) {
        return new Response('Unauthorized', { status: 401 });
      }
      try {
        const body = (await request.json()) as any;
        const installationId = body.installation_id;
        const role = body.role; // 'home_assistant' or 'device'

        if (!installationId || (role !== 'home_assistant' && role !== 'device')) {
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
        const body = (await request.json()) as any;
        const code = body.code;
        if (!code || typeof code !== 'string' || !code.includes(':')) {
          return new Response('Invalid code format', { status: 400 });
        }

        const installationId = code.split(':')[0];
        const id = env.ESP_ANYWHERE_INSTALLATION.idFromName(installationId);
        const stub = env.ESP_ANYWHERE_INSTALLATION.get(id);

        return stub.fetch(request);
      } catch (e) {
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

      let token = url.searchParams.get('token');
      const authHeader = request.headers.get('Authorization');
      if (!token && authHeader && authHeader.startsWith('Bearer ')) {
        token = authHeader.slice(7);
      }

      if (!installationId || !role || !token) {
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
