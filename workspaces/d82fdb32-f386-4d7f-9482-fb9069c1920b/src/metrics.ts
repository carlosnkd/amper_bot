/**
 * Deliberately tiny in-process counter registry. It is enough to answer
 * "how many creations were allowed vs rejected?" and to be scraped/exported by
 * whatever metrics backend gets wired in later.
 */
export type CounterName =
  | 'items_create_allowed_total'
  | 'items_create_rejected_total'
  | 'rate_limit_store_errors_total';

const counters: Record<CounterName, number> = {
  items_create_allowed_total: 0,
  items_create_rejected_total: 0,
  rate_limit_store_errors_total: 0,
};

export const metrics = {
  increment(name: CounterName, by = 1): void {
    counters[name] += by;
  },

  get(name: CounterName): number {
    return counters[name];
  },

  snapshot(): Record<CounterName, number> {
    return { ...counters };
  },

  reset(): void {
    for (const key of Object.keys(counters) as CounterName[]) {
      counters[key] = 0;
    }
  },
};
