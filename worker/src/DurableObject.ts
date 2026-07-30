import { Env } from './index';

interface ConnectedClient {
  ws: WebSocket;
  role: 'device' | 'home_assistant';
  deviceId?: string;
}

interface ActivationCode {
  code: string;
  role: 'home_assistant' | 'device';
  expiresAt: number;
}

function generateRandomString(length: number) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let result = '';
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return result;
}

export class InstallationDO {
  state: DurableObjectState;
  env: Env;

  haClient: WebSocket | null = null;
  devices: Map<string, WebSocket> = new Map();
  errorCounts: Map<WebSocket, number> = new Map();
  msgCounts: Map<WebSocket, number> = new Map();
  lastMsgReset: number = Date.now();

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/admin/activation-code') {
      const body = (await request.json()) as any;
      const installationId = body.installation_id;
      const role = body.role;

      const secret = generateRandomString(16);
      const code = `${installationId}:${secret}`;
      const expiresAt = Date.now() + 10 * 60 * 1000;

      const actCode: ActivationCode = { code, role, expiresAt };
      await this.state.storage.put(`activation_code:${code}`, actCode);

      return new Response(JSON.stringify({ code, expiresAt }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (request.method === 'POST' && url.pathname === '/claim') {
      const body = (await request.json()) as any;
      const code = body.code;

      const actCode = await this.state.storage.get<ActivationCode>(`activation_code:${code}`);
      if (!actCode) {
        return new Response('Invalid code', { status: 400 });
      }
      if (Date.now() > actCode.expiresAt) {
        await this.state.storage.delete(`activation_code:${code}`);
        return new Response('Code expired', { status: 400 });
      }

      await this.state.storage.delete(`activation_code:${code}`);
      const newToken = generateRandomString(32);

      if (actCode.role === 'home_assistant') {
        await this.state.storage.put('ha_token', newToken);
      } else {
        let deviceTokens = await this.state.storage.get<string[]>('device_tokens') || [];
        deviceTokens.push(newToken);
        await this.state.storage.put('device_tokens', deviceTokens);
      }

      return new Response(JSON.stringify({
        token: newToken,
        installation_id: code.split(':')[0],
        role: actCode.role
      }), { headers: { 'Content-Type': 'application/json' } });
    }

    if (url.pathname === '/ws') {
      const role = url.searchParams.get('role') as 'device' | 'home_assistant';
      const deviceId = url.searchParams.get('device_id');

      let token = url.searchParams.get('token');
      const authHeader = request.headers.get('Authorization');
      if (!token && authHeader && authHeader.startsWith('Bearer ')) {
        token = authHeader.slice(7);
      }

      if (role === 'home_assistant') {
        const expectedHaToken = await this.state.storage.get<string>('ha_token');
        if (!expectedHaToken || token !== expectedHaToken) {
          return new Response('Unauthorized HA token', { status: 401 });
        }
      } else if (role === 'device') {
        if (!deviceId) {
          return new Response('Missing device_id for device role', { status: 400 });
        }
        const deviceTokens = await this.state.storage.get<string[]>('device_tokens') || [];
        if (!token || !deviceTokens.includes(token)) {
          return new Response('Unauthorized device token', { status: 401 });
        }
      }

      const webSocketPair = new WebSocketPair();
      const [client, server] = Object.values(webSocketPair);

      this.state.acceptWebSocket(server);

      if (role === 'home_assistant') {
        if (this.haClient) {
          try { this.haClient.close(1000, 'Replaced'); } catch (e) {}
        }
        this.haClient = server;
        server.serializeAttachment({ role: 'home_assistant' });
        this.syncStateToHA(server);
      } else if (role === 'device' && deviceId) {
        const existing = this.devices.get(deviceId);
        if (existing) {
          try { existing.close(1000, 'Replaced'); } catch (e) {}
        }
        this.devices.set(deviceId, server);
        server.serializeAttachment({ role: 'device', deviceId });
        this.pushPresence(deviceId, true);
      }

      this.errorCounts.set(server, 0);
      this.msgCounts.set(server, 0);

      return new Response(null, {
        status: 101,
        webSocket: client,
      });
    }

    return new Response('Not found', { status: 404 });
  }

  async syncStateToHA(haClient: WebSocket) {
    const discoveries = await this.state.storage.get<Record<string, any>>('discoveries') || {};
    const states = await this.state.storage.get<Record<string, any>>('states') || {};

    for (const [devId, payload] of Object.entries(discoveries)) {
      haClient.send(JSON.stringify({ type: 'discovery', device_id: devId, payload }));
    }
    for (const [devId, payload] of Object.entries(states)) {
      haClient.send(JSON.stringify({ type: 'state', device_id: devId, payload }));
    }
    for (const devId of this.devices.keys()) {
      haClient.send(JSON.stringify({ type: 'presence', device_id: devId, payload: { online: true } }));
    }
  }

  async pushPresence(deviceId: string, online: boolean) {
    if (this.haClient) {
      this.haClient.send(JSON.stringify({
        type: 'presence',
        device_id: deviceId,
        payload: { online }
      }));
    }
  }

  enforceLimits(ws: WebSocket): boolean {
    const now = Date.now();
    if (now - this.lastMsgReset > 10000) {
        this.msgCounts.clear();
        this.lastMsgReset = now;
    }

    let cnt = this.msgCounts.get(ws) || 0;
    cnt++;
    this.msgCounts.set(ws, cnt);

    if (cnt > 50) { // Limit 50 msg per 10s
        try { ws.close(1008, 'Rate limit exceeded'); } catch (e) {}
        return false;
    }
    return true;
  }

  recordError(ws: WebSocket) {
    let errs = this.errorCounts.get(ws) || 0;
    errs++;
    this.errorCounts.set(ws, errs);
    if (errs >= 5) {
        try { ws.close(1008, 'Too many errors'); } catch (e) {}
    }
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    if (!this.enforceLimits(ws)) return;

    try {
      const msgString = typeof message === 'string' ? message : new TextDecoder().decode(message);
      if (msgString.length > 32 * 1024) {
          this.recordError(ws);
          return;
      }

      const data = JSON.parse(msgString);
      if (!data || typeof data !== 'object') {
          this.recordError(ws);
          return;
      }

      const attachment = ws.deserializeAttachment() as { role: string; deviceId?: string };
      if (!attachment) return;

      const { type, payload } = data;

      if (type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
        return;
      }

      if (attachment.role === 'device' && attachment.deviceId) {
        const deviceId = attachment.deviceId;
        if (['discovery', 'state', 'command_result', 'ota/progress'].includes(type)) {
          if (type === 'discovery') {
             let discoveries = await this.state.storage.get<Record<string, any>>('discoveries') || {};
             discoveries[deviceId] = payload;
             await this.state.storage.put('discoveries', discoveries);
          } else if (type === 'state') {
             let states = await this.state.storage.get<Record<string, any>>('states') || {};
             states[deviceId] = payload;
             await this.state.storage.put('states', states);
          }

          if (this.haClient) {
            data.device_id = deviceId;
            this.haClient.send(JSON.stringify(data));
          }
        } else {
            this.recordError(ws);
        }
      } else if (attachment.role === 'home_assistant') {
        if (type === 'command') {
          const targetDeviceId = data.device_id;
          const targetWs = this.devices.get(targetDeviceId);
          if (targetWs) {
            targetWs.send(JSON.stringify(data));
          }
        } else {
            this.recordError(ws);
        }
      }
    } catch (err) {
      this.recordError(ws);
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string, wasClean: boolean) {
    this.errorCounts.delete(ws);
    this.msgCounts.delete(ws);

    const attachment = ws.deserializeAttachment() as { role: string; deviceId?: string };
    if (!attachment) return;

    if (attachment.role === 'home_assistant') {
      if (this.haClient === ws) {
        this.haClient = null;
      }
    } else if (attachment.role === 'device' && attachment.deviceId) {
      if (this.devices.get(attachment.deviceId) === ws) {
        this.devices.delete(attachment.deviceId);
        this.pushPresence(attachment.deviceId, false);
      }
    }
  }

  async webSocketError(ws: WebSocket, error: unknown) {
    await this.webSocketClose(ws, 1006, 'Error', false);
  }
}
