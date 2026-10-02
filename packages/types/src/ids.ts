export type Brand<K, T> = K & { __brand: T };

export type UserId = Brand<string, "UserId">;
export type OrganizationId = Brand<string, "OrganizationId">;
export type MembershipId = Brand<string, "MembershipId">;
export type AgentId = Brand<string, "AgentId">;
export type WorkflowId = Brand<string, "WorkflowId">;
export type ExecutionId = Brand<string, "ExecutionId">;
export type ToolId = Brand<string, "ToolId">;
export type CredentialId = Brand<string, "CredentialId">;
export type MemoryId = Brand<string, "MemoryId">;
export type JobId = Brand<string, "JobId">;
export type RequestId = Brand<string, "RequestId">;
export type SessionId = Brand<string, "SessionId">;
export type ApiKeyId = Brand<string, "ApiKeyId">;
export type IntegrationId = Brand<string, "IntegrationId">;
export type MarketplaceItemId = Brand<string, "MarketplaceItemId">;

export function createId<T extends string>(prefix: string): Brand<string, T> {
  return `${prefix}_${crypto.randomUUID()}` as Brand<string, T>;
}

export function isValidId(id: string, prefix: string): boolean {
  return id.startsWith(`${prefix}_`);
}
