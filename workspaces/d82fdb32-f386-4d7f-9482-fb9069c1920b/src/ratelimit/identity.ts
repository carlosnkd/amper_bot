import { createHmac } from 'crypto';
import type { Request } from 'express';

export const API_KEY_HEADER = 'x-api-key';

export interface ClientIdentity {
  /** 'key' when the request carried an X-API-Key header, otherwise 'ip'. */
  type: 'key' | 'ip';
  /** Raw value — the API key or the resolved IP. Never used as a store key. */
  raw: string;
  /** Safe, stable identifier: hashed for API keys, prefixed for IPs. */
  id: string;
}

/** HMAC-SHA256, truncated: enough entropy to avoid collisions, short in logs. */
export function hashApiKey(apiKey: string, salt: string): string {
  return createHmac('sha256', salt).update(apiKey).digest('hex').slice(0, 32);
}

export function readApiKey(req: Request): string | undefined {
  const header = req.headers[API_KEY_HEADER];
  const value = Array.isArray(header) ? header[0] : header;
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

/**
 * Trust-proxy aware client IP. Express already resolves `req.ip` from
 * X-Forwarded-For according to the app's `trust proxy` setting, so we use that
 * and only fall back to the socket address.
 */
export function clientIp(req: Request): string {
  return req.ip ?? req.socket?.remoteAddress ?? 'unknown';
}

export function identifyClient(req: Request, salt: string): ClientIdentity {
  const apiKey = readApiKey(req);
  if (apiKey) {
    return { type: 'key', raw: apiKey, id: `key:${hashApiKey(apiKey, salt)}` };
  }
  const ip = clientIp(req);
  return { type: 'ip', raw: ip, id: `ip:${ip}` };
}

/**
 * Store keys are namespaced by route so the same limiter can be reused on
 * another endpoint later without the two sharing a budget.
 */
export function makeKeyGenerator(options: { route: string; salt: string }) {
  return (req: Request): string => {
    const identity = identifyClient(req, options.salt);
    return `${options.route}|${identity.id}`;
  };
}
