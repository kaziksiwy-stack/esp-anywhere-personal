import { describe, it, expect, vi, beforeEach } from 'vitest';
import { InstallationDO } from '../src/DurableObject';

describe('InstallationDO Routing & Persistence', () => {
  let mockStorage: any;
  let stubState: any;
  let doInstance: InstallationDO;
  let haSocket: any;
  let deviceSocket: any;

  beforeEach(() => {
    mockStorage = {
      data: new Map<string, any>(),
      get: vi.fn(async (key: string) => mockStorage.data.get(key)),
      put: vi.fn(async (key: string, val: any) => mockStorage.data.set(key, val)),
      delete: vi.fn(async (key: string) => mockStorage.data.delete(key)),
    };

    stubState = {
      acceptWebSocket: vi.fn(),
      storage: mockStorage,
    };

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

    doInstance = new InstallationDO(stubState as any, {} as any);
    doInstance.haClient = haSocket;
    doInstance.devices.set('test-device', deviceSocket);
  });

  it('HA receives discovery from device and caches it', async () => {
    await doInstance.webSocketMessage(deviceSocket, JSON.stringify({ type: 'discovery', payload: { foo: 'bar' } }));
    expect(haSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'discovery', payload: { foo: 'bar' }, device_id: 'test-device' }));
    expect(mockStorage.data.get('discoveries')['test-device']).toEqual({ foo: 'bar' });
  });

  it('HA receives state from device and caches it', async () => {
    await doInstance.webSocketMessage(deviceSocket, JSON.stringify({ type: 'state', payload: { power: true } }));
    expect(haSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'state', payload: { power: true }, device_id: 'test-device' }));
    expect(mockStorage.data.get('states')['test-device']).toEqual({ power: true });
  });

  it('syncStateToHA restores discovery and state', async () => {
    mockStorage.data.set('discoveries', { 'old-dev': { ver: 1 } });
    mockStorage.data.set('states', { 'old-dev': { online: true } });

    await doInstance.syncStateToHA(haSocket);
    expect(haSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'discovery', device_id: 'old-dev', payload: { ver: 1 } }));
    expect(haSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'state', device_id: 'old-dev', payload: { online: true } }));
  });

  it('Device receives command from HA', async () => {
    await doInstance.webSocketMessage(haSocket, JSON.stringify({ type: 'command', device_id: 'test-device', command: 'turn_on' }));
    expect(deviceSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'command', device_id: 'test-device', command: 'turn_on' }));
  });

  it('Device ping gets pong', async () => {
    await doInstance.webSocketMessage(deviceSocket, JSON.stringify({ type: 'ping' }));
    expect(deviceSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'pong' }));
  });
});
