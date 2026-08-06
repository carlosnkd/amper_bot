export interface RateLimitConfig {
  /** Length of the trailing window in milliseconds. */
  windowMs: number;
  /** Maximum requests allowed per client per window. */
  max: number;
  /** Raw API keys that skip the limiter entirely. */
  trustedKeys: string[];
  /** Salt mixed into the API-key hash so store keys/logs never carry raw keys. */
  keySalt: string;
}

const DEFAULT_WINDOW_MS = 60_000;
const DEFAULT_MAX = 10;

function intFromEnv(
  env: NodeJS.ProcessEnv,
  name: string,
  fallback: number,
): number {
  const raw = env[name];
  if (raw === undefined || raw.trim() === '') return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed) || parsed <= 0) return fallback;
  return parsed;
}

function listFromEnv(env: NodeJS.ProcessEnv, name: string): string[] {
  const raw = env[name];
  if (!raw) return [];
  return raw
    .split(',')
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}

/**
 * The single limit for the one guarded endpoint (`POST /api/items`).
 * There is no per-route table: every other route is unlimited by construction.
 */
export function loadCreateItemsLimitConfig(
  env: NodeJS.ProcessEnv = process.env,
): RateLimitConfig {
  return {
    windowMs: intFromEnv(env, 'RATE_LIMIT_WINDOW_MS', DEFAULT_WINDOW_MS),
    max: intFromEnv(env, 'RATE_LIMIT_MAX', DEFAULT_MAX),
    trustedKeys: listFromEnv(env, 'RATE_LIMIT_TRUSTED_KEYS'),
    keySalt: env.RATE_LIMIT_KEY_SALT ?? 'local-dev-salt',
  };
}

/** Route namespace for the guarded endpoint's store keys. */
export const CREATE_ITEMS_ROUTE = 'POST:/api/items';

/** Number of proxy hops to trust when resolving the client IP. */
export function trustProxyHops(env: NodeJS.ProcessEnv = process.env): number {
  return intFromEnv(env, 'TRUST_PROXY_HOPS', 0);
}
