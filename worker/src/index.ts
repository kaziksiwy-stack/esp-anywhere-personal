import { InstallationDO } from './DurableObject';

export interface Env {
  ESP_ANYWHERE_INSTALLATION: DurableObjectNamespace;
  AUTH_TOKEN?: string;
}

export { InstallationDO };

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const upgradeHeader = request.headers.get('Upgrade');
    if (!upgradeHeader || upgradeHeader !== 'websocket') {
      return new Response('Expected Upgrade: websocket', { status: 426 });
    }

    const url = new URL(request.url);
    const installationId = url.searchParams.get('installation_id');
    const role = url.searchParams.get('role'); // "device" or "home_assistant"

    // Support token from query param or Authorization header
    let token = url.searchParams.get('token');
    const authHeader = request.headers.get('Authorization');
    if (!token && authHeader && authHeader.startsWith('Bearer ')) {
      token = authHeader.slice(7);
    }

    if (!installationId || !role) {
      return new Response('Missing installation_id or role', { status: 400 });
    }

    if (role !== 'device' && role !== 'home_assistant') {
      return new Response('Invalid role', { status: 400 });
    }

    if (env.AUTH_TOKEN && token !== env.AUTH_TOKEN) {
      return new Response('Unauthorized', { status: 401 });
    }

    const id = env.ESP_ANYWHERE_INSTALLATION.idFromName(installationId);
    const stub = env.ESP_ANYWHERE_INSTALLATION.get(id);

    return stub.fetch(request);
  },
};
