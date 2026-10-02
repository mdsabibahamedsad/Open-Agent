import { PrismaClient } from "@prisma/client";
import { Env } from "@openagent/config";
import { getLogger } from "@openagent/logger";

let prisma: PrismaClient | null = null;

export function createPrismaClient(env: Env): PrismaClient {
  const logger = getLogger();

  const client = new PrismaClient({
    log:
      env.OPENAGENT_ENV === "development"
        ? [
            { level: "query", emit: "event" },
            { level: "error", emit: "stdout" },
            { level: "warn", emit: "stdout" },
          ]
        : [{ level: "error", emit: "stdout" }],
  });

  if (env.OPENAGENT_ENV === "development") {
    client.$on("query", (e: { query: string; duration: number }) => {
      logger.debug("Database query", {
        query: e.query,
        duration: e.duration,
      });
    });
  }

  return client;
}

export function getPrismaClient(): PrismaClient {
  if (!prisma) {
    throw new Error(
      "Prisma client not initialized. Call initializeDatabase first.",
    );
  }
  return prisma;
}

export async function initializeDatabase(env: Env): Promise<PrismaClient> {
  prisma = createPrismaClient(env);
  await prisma.$connect();
  return prisma;
}

export async function closeDatabase(): Promise<void> {
  if (prisma) {
    await prisma.$disconnect();
    prisma = null;
  }
}

export { PrismaClient } from "@prisma/client";
