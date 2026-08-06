import type { Request } from 'express';
import {
  clientIp,
  hashApiKey,
  identifyClient,
  makeKeyGenerator,
  readApiKey,
} from '../../src/ratelimit/identity';

function req(overrides: Record<string, unknown> = {}): Request {
  return {
    headers: {},
    socket: { remoteAddress: '10.0.0.9' },
    ...overrides,
  } as unknown as Request;
}

describe('client identification', () => {
  it('reads and trims the X-API-Key header', () => {
    expect(readApiKey(req({ headers: { 'x-api-key': '  abc  ' } }))).toBe('abc');
    expect(readApiKey(req({ headers: { 'x-api-key': '   ' } }))).toBeUndefined();
    expect(readApiKey(req())).toBeUndefined();
    expect(readApiKey(req({ headers: { 'x-api-key': ['first', 'second'] } }))).toBe(
      'first',
    );
  });

  it('hashes API keys deterministically and never exposes the raw value', () => {
    const hashed = hashApiKey('super-secret', 'salt');
    expect(hashed).toHaveLength(32);
    expect(hashed).toBe(hashApiKey('super-secret', 'salt'));
    expect(hashed).not.toContain('super-secret');
    expect(hashed).not.toBe(hashApiKey('super-secret', 'other-salt'));
    expect(hashed).not.toBe(hashApiKey('another-secret', 'salt'));
  });

  it('prefers the API key over the IP', () => {
    const identity = identifyClient(
      req({ headers: { 'x-api-key': 'k1' }, ip: '1.2.3.4' }),
      'salt',
    );
    expect(identity.type).toBe('key');
    expect(identity.id).toBe(`key:${hashApiKey('k1', 'salt')}`);
  });

  it('falls back to the express-resolved (trust-proxy aware) IP', () => {
    const identity = identifyClient(req({ ip: '203.0.113.7' }), 'salt');
    expect(identity.type).toBe('ip');
    expect(identity.id).toBe('ip:203.0.113.7');
  });

  it('falls back to the socket address when req.ip is absent', () => {
    expect(clientIp(req())).toBe('10.0.0.9');
    expect(clientIp({ headers: {} } as unknown as Request)).toBe('unknown');
  });

  it('namespaces the store key by route', () => {
    const generate = makeKeyGenerator({ route: 'POST:/api/items', salt: 'salt' });
    expect(generate(req({ ip: '1.1.1.1' }))).toBe('POST:/api/items|ip:1.1.1.1');

    const other = makeKeyGenerator({ route: 'POST:/api/widgets', salt: 'salt' });
    expect(other(req({ ip: '1.1.1.1' }))).not.toBe(generate(req({ ip: '1.1.1.1' })));
  });

  it('gives different API keys different store keys', () => {
    const generate = makeKeyGenerator({ route: 'POST:/api/items', salt: 'salt' });
    const a = generate(req({ headers: { 'x-api-key': 'a' } }));
    const b = generate(req({ headers: { 'x-api-key': 'b' } }));
    expect(a).not.toBe(b);
  });
});
