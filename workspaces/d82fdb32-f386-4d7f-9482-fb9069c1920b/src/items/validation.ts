import type { NextFunction, Request, Response } from 'express';
import { CreateItemInput } from './itemsRepository';

export interface ValidationFailure {
  error: 'validation_failed';
  message: string;
}

export function parseCreateItem(
  body: unknown,
): { ok: true; value: CreateItemInput } | { ok: false; message: string } {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return { ok: false, message: 'Request body must be a JSON object.' };
  }
  const record = body as Record<string, unknown>;
  const name = record.name;
  if (typeof name !== 'string' || name.trim().length === 0) {
    return { ok: false, message: '`name` is required and must be a non-empty string.' };
  }
  if (name.length > 200) {
    return { ok: false, message: '`name` must be at most 200 characters.' };
  }
  const description = record.description;
  if (
    description !== undefined &&
    description !== null &&
    typeof description !== 'string'
  ) {
    return { ok: false, message: '`description` must be a string when provided.' };
  }
  return {
    ok: true,
    value: {
      name: name.trim(),
      description: typeof description === 'string' ? description : null,
    },
  };
}

/**
 * Body validation runs *after* the limiter so that a flood of malformed
 * requests still consumes quota instead of being a free way to hammer the API.
 */
export function validateCreateItem(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  const parsed = parseCreateItem(req.body);
  if (!parsed.ok) {
    res.status(400).json({
      error: 'validation_failed',
      message: parsed.message,
    } satisfies ValidationFailure);
    return;
  }
  res.locals.createItemInput = parsed.value;
  next();
}
