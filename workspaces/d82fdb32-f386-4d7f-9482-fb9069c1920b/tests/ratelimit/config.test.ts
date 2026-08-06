import {
  CREATE_ITEMS_ROUTE,
  loadCreateItemsLimitConfig,
  trustProxyHops,
} from '../../src/ratelimit/config';

describe('rate limit config', () => {
  it('uses sane defaults when nothing is set', () => {
    const config = loadCreateItemsLimitConfig({});
    expect(config.windowMs).toBe(60_000);
    expect(config.max).toBe(10);
    expect(config.trustedKeys).toEqual([]);
    expect(config.keySalt).toBe('local-dev-salt');
  });

  it('reads overrides from the environment', () => {
    const config = loadCreateItemsLimitConfig({
      RATE_LIMIT_WINDOW_MS: '5000',
      RATE_LIMIT_MAX: '3',
      RATE_LIMIT_TRUSTED_KEYS: ' partner-a , partner-b ,,',
      RATE_LIMIT_KEY_SALT: 'pepper',
    });
    expect(config.windowMs).toBe(5000);
    expect(config.max).toBe(3);
    expect(config.trustedKeys).toEqual(['partner-a', 'partner-b']);
    expect(config.keySalt).toBe('pepper');
  });

  it('ignores unparseable or non-positive values', () => {
    const config = loadCreateItemsLimitConfig({
      RATE_LIMIT_WINDOW_MS: 'abc',
      RATE_LIMIT_MAX: '0',
    });
    expect(config.windowMs).toBe(60_000);
    expect(config.max).toBe(10);
  });

  it('names the single guarded route', () => {
    expect(CREATE_ITEMS_ROUTE).toBe('POST:/api/items');
  });

  it('defaults trust proxy hops to 0', () => {
    expect(trustProxyHops({})).toBe(0);
    expect(trustProxyHops({ TRUST_PROXY_HOPS: '2' })).toBe(2);
  });
});
