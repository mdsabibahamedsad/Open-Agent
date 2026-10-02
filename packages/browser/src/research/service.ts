/** Browser research workflow: search → open → inspect → extract → cross-check → evidence. */

export interface ResearchSource {
  url: string;
  title: string;
  accessedAt: Date;
  excerpt: string;
}

export interface ResearchResult {
  objective: string;
  summary: string;
  sources: ResearchSource[];
  structured?: Record<string, unknown>;
}

export interface ResearchPlan {
  objective: string;
  allowedDomains: string[];
  maxSteps: number;
  queries: string[];
}

export function buildResearchPlan(objective: string, allowedDomains: string[] = [], maxSteps = 25): ResearchPlan {
  const queries = [objective.slice(0, 200)];
  return { objective, allowedDomains, maxSteps, queries };
}

export function compileResearchEvidence(objective: string, sources: ResearchSource[]): ResearchResult {
  const summary = sources.map((s) => `- ${s.title} (${s.url}): ${s.excerpt.slice(0, 300)}`).join('\n');
  return { objective, summary, sources };
}
