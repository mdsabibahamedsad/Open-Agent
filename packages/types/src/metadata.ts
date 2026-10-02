import type { Timestamps } from "./timestamps.js";
import type { OrganizationId } from "./ids.js";

export interface ResourceMetadata extends Timestamps {
  organization_id: OrganizationId;
  created_by?: string;
  updated_by?: string;
  metadata?: Record<string, unknown>;
}

export interface SoftDeletable {
  deleted_at: Date | null;
}

export function isSoftDeleted(resource: SoftDeletable): boolean {
  return resource.deleted_at !== null;
}
