import bcrypt from "bcryptjs";
import { SignJWT, jwtVerify, JWTPayload } from "jose";
import { Env } from "@openagent/config";
import { getLogger } from "@openagent/logger";
import type {
  UserId,
  OrganizationId,
  SessionId,
  ApiKeyId,
} from "@openagent/types";

const logger = getLogger();

export const PASSWORD_MIN_LENGTH = 8;
export const BCRYPT_ROUNDS = 12;

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, BCRYPT_ROUNDS);
}

export async function verifyPassword(
  password: string,
  hash: string,
): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

export function validatePasswordStrength(password: string): {
  valid: boolean;
  errors: string[];
} {
  const errors: string[] = [];
  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.push(`Password must be at least ${PASSWORD_MIN_LENGTH} characters`);
  }
  if (!/[A-Z]/.test(password)) {
    errors.push("Password must contain at least one uppercase letter");
  }
  if (!/[a-z]/.test(password)) {
    errors.push("Password must contain at least one lowercase letter");
  }
  if (!/[0-9]/.test(password)) {
    errors.push("Password must contain at least one number");
  }
  return { valid: errors.length === 0, errors };
}

interface TokenPayload extends JWTPayload {
  sub: string;
  type:
    "access" | "refresh" | "api_key" | "email_verification" | "password_reset";
  organization_id?: string;
  permissions?: string[];
}

function getSecretKey(env: Env): Uint8Array {
  return new TextEncoder().encode(env.SECRET_KEY);
}

export async function createAccessToken(
  env: Env,
  userId: UserId,
  organizationId?: OrganizationId,
  permissions: string[] = [],
  expiresIn: string = "15m",
): Promise<string> {
  const secret = getSecretKey(env);
  return new SignJWT({
    sub: userId,
    type: "access",
    organization_id: organizationId,
    permissions,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(expiresIn)
    .sign(secret);
}

export async function createRefreshToken(
  env: Env,
  userId: UserId,
  sessionId: SessionId,
  expiresIn: string = "30d",
): Promise<string> {
  const secret = getSecretKey(env);
  return new SignJWT({ sub: userId, type: "refresh", session_id: sessionId })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(expiresIn)
    .sign(secret);
}

export async function createApiKeyToken(
  env: Env,
  apiKeyId: ApiKeyId,
  organizationId: OrganizationId,
  permissions: string[] = [],
  expiresIn?: string,
): Promise<string> {
  const secret = getSecretKey(env);
  const jwt = new SignJWT({
    sub: apiKeyId,
    type: "api_key",
    organization_id: organizationId,
    permissions,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt();
  if (expiresIn) {
    jwt.setExpirationTime(expiresIn);
  }
  return jwt.sign(secret);
}

export async function verifyToken(
  env: Env,
  token: string,
): Promise<TokenPayload> {
  const secret = getSecretKey(env);
  try {
    const { payload } = await jwtVerify(token, secret);
    return payload as unknown as TokenPayload;
  } catch (error) {
    logger.warn("Token verification failed", {
      error: (error as Error).message,
    });
    throw new Error("Invalid or expired token");
  }
}

export async function verifyAccessToken(
  env: Env,
  token: string,
): Promise<TokenPayload> {
  const payload = await verifyToken(env, token);
  if (payload.type !== "access") {
    throw new Error("Invalid token type");
  }
  return payload;
}

export async function verifyRefreshToken(
  env: Env,
  token: string,
): Promise<TokenPayload> {
  const payload = await verifyToken(env, token);
  if (payload.type !== "refresh") {
    throw new Error("Invalid token type");
  }
  return payload;
}

export async function verifyApiKeyToken(
  env: Env,
  token: string,
): Promise<TokenPayload> {
  const payload = await verifyToken(env, token);
  if (payload.type !== "api_key") {
    throw new Error("Invalid token type");
  }
  return payload;
}

export function generateApiKey(): {
  key: string;
  prefix: string;
  hash: string;
} {
  const randomBytes = crypto.getRandomValues(new Uint8Array(32));
  const key = `oa_${Array.from(randomBytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
  const prefix = key.slice(0, 12);
  const hash = bcrypt.hashSync(key, BCRYPT_ROUNDS);
  return { key, prefix, hash };
}

export function generateSecureToken(length: number = 32): string {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function constantTimeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}
