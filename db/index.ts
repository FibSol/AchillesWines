import { drizzle } from "drizzle-orm/better-sqlite3";
import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import * as schema from "./schema";

const dbPath = process.env.DATABASE_URL ?? "data/achilles.db";
mkdirSync(dirname(dbPath), { recursive: true });

// Singleton: Turbopack evaluates this module concurrently across routes during
// HMR, creating competing connections. globalThis survives hot-reloads and
// ensures only one Database instance (and one WAL lock) ever exists.
declare global {
  // eslint-disable-next-line no-var
  var __achillesSqlite: Database.Database | undefined;
}

if (!globalThis.__achillesSqlite) {
  const sqlite = new Database(dbPath);
  sqlite.pragma("journal_mode = WAL");
  sqlite.pragma("synchronous = NORMAL");
  sqlite.pragma("cache_size = -64000");
  sqlite.pragma("foreign_keys = ON");
  sqlite.pragma("temp_store = MEMORY");
  globalThis.__achillesSqlite = sqlite;
}

export const db = drizzle(globalThis.__achillesSqlite, { schema, logger: process.env.DRIZZLE_LOG === "1" });
export { schema };
