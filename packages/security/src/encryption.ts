import { createCipheriv, createDecipheriv, randomBytes, createHash } from 'crypto';
import { Env } from '@openagent/config';
import { getLogger } from '@openagent/logger';

const logger = getLogger();
const ALGORITHM = 'aes-256-gcm';
const IV_LENGTH = 12;
const AUTH_TAG_LENGTH = 16;

function getEncryptionKey(env: Env): Buffer {
  const key = env.ENCRYPTION_KEY;
  if (key.length !== 64) {
    throw new Error('ENCRYPTION_KEY must be 64 hex characters (32 bytes)');
  }
  return Buffer.from(key, 'hex');
}

export async function encryptSecret(env: Env, plaintext: string): Promise<string> {
  try {
    const key = getEncryptionKey(env);
    const iv = randomBytes(IV_LENGTH);
    const cipher = createCipheriv(ALGORITHM, key, iv);
    
    const encrypted = Buffer.concat([
      cipher.update(plaintext, 'utf8'),
      cipher.final(),
    ]);
    
    const authTag = cipher.getAuthTag();
    
    const combined = Buffer.concat([iv, encrypted, authTag]);
    return combined.toString('base64');
  } catch (error) {
    logger.error('Encryption failed', {}, error as Error);
    throw new Error('Failed to encrypt secret');
  }
}

export async function decryptSecret(env: Env, ciphertext: string): Promise<string> {
  try {
    const key = getEncryptionKey(env);
    const combined = Buffer.from(ciphertext, 'base64');
    
    const iv = combined.slice(0, IV_LENGTH);
    const authTag = combined.slice(-AUTH_TAG_LENGTH);
    const encrypted = combined.slice(IV_LENGTH, -AUTH_TAG_LENGTH);
    
    const decipher = createDecipheriv(ALGORITHM, key, iv);
    decipher.setAuthTag(authTag);
    
    const decrypted = Buffer.concat([
      decipher.update(encrypted),
      decipher.final(),
    ]);
    
    return decrypted.toString('utf8');
  } catch (error) {
    logger.error('Decryption failed', {}, error as Error);
    throw new Error('Failed to decrypt secret');
  }
}

export async function hashSecret(secret: string): Promise<string> {
  const hash = createHash('sha256');
  hash.update(secret);
  return hash.digest('hex');
}

export function verifySecretHash(secret: string, hash: string): Promise<boolean> {
  return hashSecret(secret).then((computed) => constantTimeCompare(computed, hash));
}

function constantTimeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}