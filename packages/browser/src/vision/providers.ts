/** Visual understanding abstractions: OCR + visual grounding (provider-neutral). */
import type { BoundingBox } from "../core/types";

export interface OCRResult {
  text: string;
  confidence: number;
  blocks: Array<{ text: string; confidence: number; box?: BoundingBox }>;
}

export interface OCRProvider {
  readonly providerId: string;
  extractText(image: Uint8Array, mimeType?: string): Promise<OCRResult>;
}

/** Works without any provider: returns empty result so the engine degrades to DOM/AX. */
export class NoopOCRProvider implements OCRProvider {
  readonly providerId = "noop";
  async extractText(): Promise<OCRResult> {
    return { text: "", confidence: 0, blocks: [] };
  }
}

export interface GroundedElement {
  description: string;
  box: BoundingBox;
  confidence: number;
}

export interface VisualGroundingProvider {
  readonly providerId: string;
  ground(image: Uint8Array, description: string): Promise<GroundedElement[]>;
}

export class NoopVisualGroundingProvider implements VisualGroundingProvider {
  readonly providerId = "noop";
  async ground(): Promise<GroundedElement[]> {
    return [];
  }
}
