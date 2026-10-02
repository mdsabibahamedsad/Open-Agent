import { z } from "zod";

export const EnvSchema = z.object({
  OPENAGENT_ENV: z
    .enum(["development", "staging", "production"])
    .default("development"),
  LOG_LEVEL: z.enum(["debug", "info", "warn", "error"]).default("info"),
  API_URL: z.string().url().default("http://localhost:8000"),
  WEB_URL: z.string().url().default("http://localhost:3000"),
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().min(1),
  SECRET_KEY: z.string().min(32),
  ENCRYPTION_KEY: z.string().min(32),
  CORS_ORIGINS: z
    .string()
    .default("http://localhost:3000,http://localhost:8000"),
});

export type Env = z.infer<typeof EnvSchema>;

export const CorsOriginsSchema = z.string().transform((val) =>
  val
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
);

export function parseEnv(
  env: Record<string, string | undefined> = process.env,
): Env {
  return EnvSchema.parse(env);
}

export function getCorsOrigins(origins: string): string[] {
  return CorsOriginsSchema.parse(origins);
}

export function isDevelopment(env: Env): boolean {
  return env.OPENAGENT_ENV === "development";
}

export function isProduction(env: Env): boolean {
  return env.OPENAGENT_ENV === "production";
}
