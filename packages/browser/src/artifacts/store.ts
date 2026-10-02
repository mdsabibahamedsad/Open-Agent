/** Artifact abstraction over the platform storage layer. */
export interface ArtifactRecord {
  artifactId: string;
  organizationId: string;
  taskId?: string;
  sessionId?: string;
  type:
    | "screenshot"
    | "download"
    | "extraction"
    | "html"
    | "har"
    | "video"
    | "trace";
  name: string;
  size: number;
  mimeType: string;
  storageRef: string;
  createdAt: Date;
  expiresAt?: Date;
}

export interface StorageBackend {
  put(ref: string, data: Uint8Array, mimeType: string): Promise<void>;
  get(ref: string): Promise<Uint8Array>;
  delete(ref: string): Promise<void>;
}

export class InMemoryStorageBackend implements StorageBackend {
  private store = new Map<string, { data: Uint8Array; mimeType: string }>();
  async put(ref: string, data: Uint8Array, mimeType: string): Promise<void> {
    this.store.set(ref, { data, mimeType });
  }
  async get(ref: string): Promise<Uint8Array> {
    const v = this.store.get(ref);
    if (!v) throw new Error(`Artifact ${ref} not found`);
    return v.data;
  }
  async delete(ref: string): Promise<void> {
    this.store.delete(ref);
  }
}

export const MAX_ARTIFACT_BYTES = 100 * 1024 * 1024;

export function validateArtifactSize(size: number): void {
  if (size > MAX_ARTIFACT_BYTES) throw new Error("Artifact exceeds size limit");
}
