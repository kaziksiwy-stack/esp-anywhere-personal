import { Env } from './index';

interface ConnectedClient {
  ws: WebSocket;
  role: 'device' | 'home_assistant';
  deviceId?: string;
}

export class InstallationDO {
  state: DurableObjectState;
  env: Env;

  haClient: WebSocket | null = null;
  devices: Map<string, WebSocket> = new Map();

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request: Request) {
    const url = new URL(request.url);
    const role = url.searchParams.get('role') as 'device' | 'home_assistant';
    const deviceId = url.searchParams.get('device_id');

    if (role === 'device' && !deviceId) {
      return new Response('Missing device_id for device role', { status: 400 });
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
    } else if (role === 'device' && deviceId) {
      const existing = this.devices.get(deviceId);
      if (existing) {
        try { existing.close(1000, 'Replaced'); } catch (e) {}
      }
      this.devices.set(deviceId, server);
      server.serializeAttachment({ role: 'device', deviceId });
    }

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    try {
      const data = typeof message === 'string' ? JSON.parse(message) : null;
      if (!data || typeof data !== 'object') return;

      const attachment = ws.deserializeAttachment() as { role: string; deviceId?: string };
      if (!attachment) return;

      const { type } = data;

      if (type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
        return;
      }

      if (attachment.role === 'device') {
        // Forward to HA
        if (['discovery', 'state', 'command_result'].includes(type) && this.haClient) {
          data.device_id = attachment.deviceId; // Inject source device_id
          this.haClient.send(JSON.stringify(data));
        }
      } else if (attachment.role === 'home_assistant') {
        // Forward to Device
        if (type === 'command') {
          const targetDeviceId = data.device_id;
          const targetWs = this.devices.get(targetDeviceId);
          if (targetWs) {
            targetWs.send(JSON.stringify(data));
          }
        }
      }
    } catch (err) {
      // Ignore parsing errors, don't crash DO
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string, wasClean: boolean) {
    const attachment = ws.deserializeAttachment() as { role: string; deviceId?: string };
    if (!attachment) return;

    if (attachment.role === 'home_assistant') {
      if (this.haClient === ws) {
        this.haClient = null;
      }
    } else if (attachment.role === 'device' && attachment.deviceId) {
      if (this.devices.get(attachment.deviceId) === ws) {
        this.devices.delete(attachment.deviceId);
      }
    }
  }

  async webSocketError(ws: WebSocket, error: unknown) {
    await this.webSocketClose(ws, 1006, 'Error', false);
  }
}
