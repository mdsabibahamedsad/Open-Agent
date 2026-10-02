import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger: OpenAgentLogger = createChildLogger({ module: 'tool-system:credentials' });

export interface CredentialData {
  id: string;
  type: string;
  data: Record<string, unknown>;
  expires_at?: Date;
}

export interface CredentialReference {
  credential_id: string;
  fields?: string[];
}

export class CredentialResolver {
  private credentialStore: Map<string, CredentialData> = new Map();
  private organizationCredentials: Map<string, Map<string, CredentialData>> = new Map();

  constructor() {}

  registerCredential(orgId: string, credential: CredentialData): void {
    const orgCreds = this.organizationCredentials.get(orgId) || new Map();
    orgCreds.set(credential.id, credential);
    this.organizationCredentials.set(orgId, orgCreds);
    this.credentialStore.set(credential.id, credential);

    logger.info('Credential registered', { credential_id: credential.id, organization_id: orgId });
  }

  unregisterCredential(orgId: string, credentialId: string): boolean {
    const orgCreds = this.organizationCredentials.get(orgId);
    if (!orgCreds) return false;

    const removed = orgCreds.delete(credentialId);
    this.credentialStore.delete(credentialId);

    if (removed) {
      logger.info('Credential unregistered', { credential_id: credentialId, organization_id: orgId });
    }
    return removed;
  }

  async resolve(
    references: string[],
    organizationId: string
  ): Promise<Record<string, unknown>> {
    const result: Record<string, unknown> = {};

    for (const ref of references) {
      const credential = await this.getCredential(organizationId, ref);
      if (!credential) {
        logger.warn('Credential not found', { credential_id: ref, organization_id: organizationId });
        continue;
      }

      if (credential.expires_at && credential.expires_at < new Date()) {
        logger.warn('Credential expired', { credential_id: ref, organization_id: organizationId });
        continue;
      }

      result[ref] = credential.data;
    }

    return result;
  }

  async resolveFields(
    references: CredentialReference[],
    organizationId: string
  ): Promise<Record<string, unknown>> {
    const result: Record<string, unknown> = {};

    for (const ref of references) {
      const credential = await this.getCredential(organizationId, ref.credential_id);
      if (!credential) {
        logger.warn('Credential not found', { credential_id: ref.credential_id, organization_id: organizationId });
        continue;
      }

      if (credential.expires_at && credential.expires_at < new Date()) {
        logger.warn('Credential expired', { credential_id: ref.credential_id, organization_id: organizationId });
        continue;
      }

      if (ref.fields && ref.fields.length > 0) {
        const filtered: Record<string, unknown> = {};
        for (const field of ref.fields) {
          if (field in credential.data) {
            filtered[field] = credential.data[field];
          }
        }
        result[ref.credential_id] = filtered;
      } else {
        result[ref.credential_id] = credential.data;
      }
    }

    return result;
  }

  private async getCredential(
    organizationId: string,
    credentialId: string
  ): Promise<CredentialData | undefined> {
    const orgCreds = this.organizationCredentials.get(organizationId);
    if (orgCreds) {
      return orgCreds.get(credentialId);
    }
    return this.credentialStore.get(credentialId);
  }

  getCredentialData(credentialId: string): CredentialData | undefined {
    return this.credentialStore.get(credentialId);
  }

  listCredentials(organizationId: string): CredentialData[] {
    const orgCreds = this.organizationCredentials.get(organizationId);
    if (orgCreds) {
      return Array.from(orgCreds.values());
    }
    return [];
  }
}

export class CredentialManager {
  private resolver: CredentialResolver;

  constructor(resolver: CredentialResolver) {
    this.resolver = resolver;
  }

  async createCredential(
    organizationId: string,
    credentialId: string,
    type: string,
    data: Record<string, unknown>,
    expiresAt?: Date
  ): Promise<CredentialData> {
    const credential: CredentialData = {
      id: credentialId,
      type,
      data,
      expires_at: expiresAt,
    };

    this.resolver.registerCredential(organizationId, credential);
    return credential;
  }

  async updateCredential(
    organizationId: string,
    credentialId: string,
    data: Record<string, unknown>
  ): Promise<CredentialData | undefined> {
    const credential = this.resolver.getCredentialData(credentialId);
    if (!credential) return undefined;

    credential.data = { ...credential.data, ...data };
    this.resolver.registerCredential(organizationId, credential);
    return credential;
  }

  async deleteCredential(organizationId: string, credentialId: string): Promise<boolean> {
    return this.resolver.unregisterCredential(organizationId, credentialId);
  }

  async rotateCredential(
    organizationId: string,
    credentialId: string,
    newData: Record<string, unknown>
  ): Promise<CredentialData | undefined> {
    const credential = this.resolver.getCredentialData(credentialId);
    if (!credential) return undefined;

    credential.data = newData;
    this.resolver.registerCredential(organizationId, credential);
    return credential;
  }
}