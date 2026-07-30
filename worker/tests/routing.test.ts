import { describe, it, expect, vi, beforeEach } from 'vitest';
import { InstallationDO } from '../src/DurableObject';

describe('InstallationDO Routing', () => {
  let stubState: any;
  let doInstance: InstallationDO;
  let haSocket: any;
  let deviceSocket: any;

  beforeEach(() => {
    haSocket = {
      send: vi.fn(),
      close: vi.fn(),
      deserializeAttachment: vi.fn().mockReturnValue({ role: 'home_assistant' }),
    };

    deviceSocket = {
      send: vi.fn(),
      close: vi.fn(),
      deserializeAttachment: vi.fn().mockReturnValue({ role: 'device', deviceId: 'test-device' }),
    };

    stubState = {
      acceptWebSocket: vi.fn(),
    };

    doInstance = new InstallationDO(stubState as any, {} as any);
    doInstance.haClient = haSocket;
    doInstance.devices.set('test-device', deviceSocket);
  });

  it('HA receives discovery from device', async () => {
    await doInstance.webSocketMessage(deviceSocket, JSON.stringify({ type: 'discovery', payload: {} }));
    expect(haSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'discovery', payload: {}, device_id: 'test-device' }));
  });

  it('HA receives state from device', async () => {
    await doInstance.webSocketMessage(deviceSocket, JSON.stringify({ type: 'state', payload: { power: true } }));
    expect(haSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'state', payload: { power: true }, device_id: 'test-device' }));
  });

  it('Device receives command from HA', async () => {
    await doInstance.webSocketMessage(haSocket, JSON.stringify({ type: 'command', device_id: 'test-device', command: 'turn_on' }));
    expect(deviceSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'command', device_id: 'test-device', command: 'turn_on' }));
  });

  it('Device ping gets pong', async () => {
    await doInstance.webSocketMessage(deviceSocket, JSON.stringify({ type: 'ping' }));
    expect(deviceSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'pong' }));
  });

  it('Invalid JSON is ignored without crashing', async () => {
    await doInstance.webSocketMessage(deviceSocket, "invalid json");
    expect(haSocket.send).not.toHaveBeenCalled();
  });
});
