import { buildApp } from './app';
import { logger } from './logger';

const port = Number.parseInt(process.env.PORT ?? '3000', 10);
const { app, store } = buildApp();

const server = app.listen(port, () => {
  logger.info('server_listening', { port, rateLimitStore: store.kind });
});

async function shutdown(signal: string): Promise<void> {
  logger.info('server_shutting_down', { signal });
  server.close(() => {
    void store.close().then(() => process.exit(0));
  });
}

process.on('SIGTERM', () => void shutdown('SIGTERM'));
process.on('SIGINT', () => void shutdown('SIGINT'));
