export interface Timestamps {
  created_at: Date;
  updated_at: Date;
  deleted_at?: Date | null;
}

export interface CreatedAtOnly {
  created_at: Date;
}

export function now(): Date {
  return new Date();
}

export function toISOString(date: Date): string {
  return date.toISOString();
}

export function fromISOString(iso: string): Date {
  return new Date(iso);
}
