import { randomUUID } from 'crypto';

export interface Item {
  id: string;
  name: string;
  description: string | null;
  createdAt: string;
}

export interface CreateItemInput {
  name: string;
  description?: string | null;
}

/** In-memory item storage — the domain is not the point of this exercise. */
export class ItemsRepository {
  private readonly items = new Map<string, Item>();

  create(input: CreateItemInput): Item {
    const item: Item = {
      id: randomUUID(),
      name: input.name,
      description: input.description ?? null,
      createdAt: new Date().toISOString(),
    };
    this.items.set(item.id, item);
    return item;
  }

  list(): Item[] {
    return Array.from(this.items.values());
  }

  clear(): void {
    this.items.clear();
  }
}
