import { Router, type RequestHandler } from 'express';
import { CreateItemInput, ItemsRepository } from './itemsRepository';
import { validateCreateItem } from './validation';

export interface ItemsRouterOptions {
  repository: ItemsRepository;
  /**
   * The rate limiter for the creation endpoint. It is mounted on
   * `POST /api/items` only — ahead of body validation — so every other route on
   * this router stays unlimited.
   */
  createLimiter: RequestHandler;
}

export function createItemsRouter(options: ItemsRouterOptions): Router {
  const { repository, createLimiter } = options;
  const router = Router();

  // Unlimited: reads are cheap and prove the limiter is scoped to creation.
  router.get('/items', (_req, res) => {
    const items = repository.list();
    res.status(200).json({ items, count: items.length });
  });

  // Limiter first, then validation, then the handler.
  router.post('/items', createLimiter, validateCreateItem, (_req, res) => {
    const input = res.locals.createItemInput as CreateItemInput;
    const item = repository.create(input);
    res.status(201).json({ item });
  });

  return router;
}
