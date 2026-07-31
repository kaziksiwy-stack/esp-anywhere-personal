import { describe, it, expect, vi, beforeEach } from 'vitest';
import { InstallationDO, generateRandomString } from '../src/DurableObject';

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
      getWebSockets: vi.fn().mockReturnValue([]),
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
  it('generates unique hexadecimal secrets with the requested entropy', () => {
    const values = new Set(Array.from({ length: 32 }, () => generateRandomString(16)));
    expect(values.size).toBe(32);
    for (const value of values) expect(value).toMatch(/^[0-9a-f]{32}$/);
  });

  it('binds every device token to exactly one device and role', async () => {
    mockStorage.data.set('ha_token', 'ha-secret');
    mockStorage.data.set('device_tokens', {
      'device-a': { deviceId: 'device-a', token: 'device-a-secret' },
      'device-b': { deviceId: 'device-b', token: 'device-b-secret' },
    });
    await expect(doInstance.isAuthorized('device', 'device-a', 'device-a-secret')).resolves.toBe(true);
    await expect(doInstance.isAuthorized('device', 'device-b', 'device-a-secret')).resolves.toBe(false);
    await expect(doInstance.isAuthorized('device', 'device-a', 'ha-secret')).resolves.toBe(false);
    await expect(doInstance.isAuthorized('home_assistant', null, 'device-a-secret')).resolves.toBe(false);
    await expect(doInstance.isAuthorized('home_assistant', null, 'ha-secret')).resolves.toBe(true);
  });

  it('restores HA and device sockets after hibernation', () => {
    const restoredHa = { deserializeAttachment: vi.fn().mockReturnValue({ role: 'home_assistant' }) };
    const restoredDevice = { deserializeAttachment: vi.fn().mockReturnValue({ role: 'device', deviceId: 'restored-device' }) };
    stubState.getWebSockets.mockReturnValue([restoredHa, restoredDevice]);
    const restored = new InstallationDO(stubState as any, {} as any);
    expect(restored.haClient).toBe(restoredHa);
    expect(restored.devices.get('restored-device')).toBe(restoredDevice);
  });
  it('replaces only a reconnecting socket with the same identity', () => {
    const oldDevice = { close: vi.fn(), deserializeAttachment: vi.fn().mockReturnValue({ role: 'device', deviceId: 'device-a' }) };
    const otherDevice = { close: vi.fn(), deserializeAttachment: vi.fn().mockReturnValue({ role: 'device', deviceId: 'device-b' }) };
    stubState.getWebSockets.mockReturnValue([oldDevice, otherDevice]);
    const restored = new InstallationDO(stubState as any, {} as any);
    const replacement = { close: vi.fn(), serializeAttachment: vi.fn() };
    restored.registerWebSocket(replacement as any, 'device', 'device-a');
    expect(oldDevice.close).toHaveBeenCalledWith(1000, 'Replaced');
    expect(otherDevice.close).not.toHaveBeenCalled();
    expect(restored.devices.get('device-a')).toBe(replacement);
  });
});
