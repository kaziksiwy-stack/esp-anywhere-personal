import { Env } from './index';

interface ConnectedClient {
  ws: WebSocket;
  role: 'device' | 'home_assistant';
  deviceId?: string;
}

interface ActivationCode {
  code: string;
  role: 'home_assistant' | 'device';
  installationId: string;
  expiresAt: number;
  deviceId?: string;
}

interface DeviceCredential {
  deviceId: string;
  token: string;
}

interface AuditEvent { event: 'device_activation_created'; deviceId: string; timestamp: number; }
const ACTIVATION_TTL_MS = 5 * 60 * 1000;
const RATE_WINDOW_MS = 60 * 1000;
const RATE_LIMIT = 5;
const MAX_DEVICES = 64;
const DEVICE_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{2,63}$/;
const OTA_CHANNELS = new Set(["stable", "beta", "recovery"]);

function isOtaStart(data: any): boolean {
  return data?.type === "ota_start"
    && typeof data.device_id === "string"
    && DEVICE_ID_PATTERN.test(data.device_id)
    && typeof data.command_id === "string"
    && /^[0-9a-f-]{16,64}$/i.test(data.command_id)
    && OTA_CHANNELS.has(data.channel)
    && typeof data.target_version === "string"
    && /^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$/.test(data.target_version)
    && typeof data.recovery === "boolean"
    && (!data.recovery || data.channel === "recovery")
    && !("url" in data) && !("sha256" in data) && !("signature" in data);
}


export function generateRandomString(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
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
    this.restoreWebSockets();
  }

  restoreWebSockets() {
    for (const ws of this.state.getWebSockets()) {
      const attachment = ws.deserializeAttachment() as
        | { role: string; deviceId?: string }
        | null;
      if (attachment?.role === 'home_assistant') {
        this.haClient = ws;
      } else if (attachment?.role === 'device' && attachment.deviceId) {
        this.devices.set(attachment.deviceId, ws);
      }
      this.errorCounts.set(ws, 0);
      this.msgCounts.set(ws, 0);
    }
  }

  async registerWebSocket(
    server: WebSocket,
    role: 'device' | 'home_assistant',
    deviceId: string | null,
  ) {
    if (role === 'home_assistant') {
      if (this.haClient && this.haClient !== server) {
        try { this.haClient.close(1000, 'Replaced'); } catch (e) {}
      }
      this.haClient = server;
      server.serializeAttachment({ role: 'home_assistant' });
      await this.syncStateToHA(server);
    } else if (deviceId) {
      const existing = this.devices.get(deviceId);
      if (existing && existing !== server) {
        try { existing.close(1000, 'Replaced'); } catch (e) {}
      }
      this.devices.set(deviceId, server);
      server.serializeAttachment({ role: 'device', deviceId });
      this.pushPresence(deviceId, true);
      console.log(JSON.stringify({ event: "device_connected", device_id: deviceId }));
    }
    this.errorCounts.set(server, 0);
    this.msgCounts.set(server, 0);
  }

  async isAuthorized(
    role: 'device' | 'home_assistant',
    deviceId: string | null,
    token: string | null,
  ): Promise<boolean> {
    if (role === 'home_assistant') {
      const expected = await this.state.storage.get<string>('ha_token');
      return Boolean(expected && token === expected);
    }
    if (!deviceId || !token) return false;
    const credentials =
      await this.state.storage.get<Record<string, DeviceCredential>>('device_tokens') || {};
    const credential = credentials[deviceId];
    return Boolean(
      credential
      && credential.deviceId === deviceId
      && credential.token === token
    );
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === 'POST' && url.pathname === '/admin/activation-code') {
      const body = (await request.json()) as any;
      const installationId = body.installation_id;
      const role = body.role;
      const deviceId = body.device_id || undefined;

      const secret = generateRandomString(12);
      const code = `${installationId}:${secret}`;
      const expiresAt = Date.now() + 10 * 60 * 1000;

      const actCode: ActivationCode = { code, role, installationId, expiresAt, deviceId };
      await this.state.storage.put(`activation_code:${code}`, actCode);

      return new Response(JSON.stringify({ code, expiresAt }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (request.method === 'POST' && url.pathname === '/ha/device-activation-code') {
      const body = (await request.json()) as any;
      const installationId = body.installation_id;
      const deviceId = body.device_id;
      const authHeader = request.headers.get('Authorization');
      const token = authHeader?.startsWith('Bearer ') ? authHeader.slice(7) : null;
      if (!await this.isAuthorized('home_assistant', null, token)) return new Response('Unauthorized', { status: 401 });
      const deviceTokens = await this.state.storage.get<Record<string, DeviceCredential>>('device_tokens') || {};
      if (Object.keys(deviceTokens).length >= MAX_DEVICES) return new Response('Device limit reached', { status: 409 });
      if (deviceTokens[deviceId]) return new Response('Device already exists', { status: 409 });
      const now = Date.now();
      const issued = (await this.state.storage.get<number[]>('ha_activation_issued') || []).filter(timestamp => now - timestamp < RATE_WINDOW_MS);
      if (issued.length >= RATE_LIMIT) return new Response('Rate limit exceeded', { status: 429 });
      const pending = await this.state.storage.get<Record<string, number>>('pending_device_ids') || {};
      for (const [id, expiresAt] of Object.entries(pending)) if (expiresAt <= now) delete pending[id];
      if (pending[deviceId]) return new Response('Device activation already pending', { status: 409 });
      const code = `${installationId}:${generateRandomString(12)}`;
      const expiresAt = now + ACTIVATION_TTL_MS;
      const actCode: ActivationCode = { code, role: 'device', installationId, expiresAt, deviceId };
      pending[deviceId] = expiresAt;
      issued.push(now);
      const audit = await this.state.storage.get<AuditEvent[]>('audit_events') || [];
      audit.push({ event: 'device_activation_created', deviceId, timestamp: now });
      await this.state.storage.put(`activation_code:${code}`, actCode);
      await this.state.storage.put('pending_device_ids', pending);
      await this.state.storage.put('ha_activation_issued', issued);
      await this.state.storage.put('audit_events', audit.slice(-100));
      return Response.json({ code, expiresAt, installation_id: installationId, device_id: deviceId }, { headers: { 'Cache-Control': 'no-store' } });
    }

    if (request.method === 'POST' && url.pathname === '/claim') {
      const body = (await request.json()) as any;
      const code = body.code;
      const deviceId = body.device_id;
      const actCode = await this.state.storage.get<ActivationCode>(`activation_code:${code}`);
      if (!actCode) return new Response('Invalid code', { status: 400 });
      if (Date.now() > actCode.expiresAt) {
        await this.state.storage.delete(`activation_code:${code}`);
        return new Response('Code expired', { status: 400 });
      }
      const codeInstallationId = typeof code === 'string' ? code.split(':', 1)[0] : '';
      if (codeInstallationId !== actCode.installationId) return new Response('Installation mismatch', { status: 400 });
      if (actCode.role === 'device' && (typeof deviceId !== 'string' || !/^[a-z0-9][a-z0-9_-]{2,63}$/.test(deviceId))) return new Response('Missing or invalid device_id', { status: 400 });
      if (actCode.role === 'device' && actCode.deviceId !== deviceId) return new Response('Device mismatch', { status: 400 });
      await this.state.storage.delete(`activation_code:${code}`);
      if (actCode.role === 'device') {
        const pending = await this.state.storage.get<Record<string, number>>('pending_device_ids') || {};
        delete pending[deviceId];
        await this.state.storage.put('pending_device_ids', pending);
      }
      const newToken = generateRandomString(32);
      if (actCode.role === 'home_assistant') await this.state.storage.put('ha_token', newToken);
      else {
        const deviceTokens = await this.state.storage.get<Record<string, DeviceCredential>>('device_tokens') || {};
        deviceTokens[deviceId] = { deviceId, token: newToken };
        await this.state.storage.put('device_tokens', deviceTokens);
      }
      return new Response(JSON.stringify({ token: newToken, installation_id: actCode.installationId, role: actCode.role }), { headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
    }

    if (url.pathname === '/ws') {
      const role = url.searchParams.get('role') as 'device' | 'home_assistant';
      const deviceId = url.searchParams.get('device_id');

      const authHeader = request.headers.get('Authorization');
      const token = authHeader?.startsWith('Bearer ')
        ? authHeader.slice(7)
        : null;

      if (role === 'device' && !deviceId) {
        return new Response('Missing device_id for device role', { status: 400 });
      }
      if (!await this.isAuthorized(role, deviceId, token)) {
        return new Response('Unauthorized token', { status: 401 });
      }

      const webSocketPair = new WebSocketPair();
      const [client, server] = Object.values(webSocketPair);

      this.state.acceptWebSocket(server);

      await this.registerWebSocket(server, role, deviceId);

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
    console.log(JSON.stringify({ event: "ha_state_replay", discoveries: Object.keys(discoveries).length, states: Object.keys(states).length, online_devices: this.devices.size }));

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

  enforceLimits(ws: WebSocket, limit = 50): boolean {
    const now = Date.now();
    if (now - this.lastMsgReset > 10000) {
        this.msgCounts.clear();
        this.lastMsgReset = now;
    }

    let cnt = this.msgCounts.get(ws) || 0;
    cnt++;
    this.msgCounts.set(ws, cnt);

    if (cnt > limit) { // Limit 50 msg per 10s
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

      const { type, payload } = data;
      const otaBurst = attachment.role === "device" && ["ota_progress", "ota_verify", "ota_success", "ota_failed", "ota_rollback"].includes(String(type));
      if (!this.enforceLimits(ws, otaBurst ? 400 : 50)) return;

      if (type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
        return;
      }

      if (attachment.role === 'device' && attachment.deviceId) {
        const deviceId = attachment.deviceId;
        if (['discovery', 'state', 'command_result', 'ota/progress', 'ota_progress', 'ota_verify', 'ota_success', 'ota_failed', 'ota_rollback'].includes(type)) {
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
        console.log(JSON.stringify({ event: "ha_message", type: String(type), device_id: typeof data.device_id === "string" ? data.device_id : null }));
        if (type === 'command' || (type === 'ota_start' && isOtaStart(data))) {
          const targetDeviceId = data.device_id;
          const targetWs = this.devices.get(targetDeviceId);
          if (type === "ota_start") console.log(JSON.stringify({ event: "ota_routed", device_id: targetDeviceId, online: Boolean(targetWs) }));
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
