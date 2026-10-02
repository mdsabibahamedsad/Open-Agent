// MP22: typed client for packages / skills / presets / catalog / installations.

import { api } from '@/lib/api';

export interface PackageSummary {
  id: string;
  organization_id: string | null;
  slug: string;
  name: string;
  description: string;
  package_type: string;
  visibility: string;
  trust: string;
  official: boolean;
  license: string;
  author_name: string;
  publisher: string;
  categories: string[];
  tags: string[];
  latest_version: string;
  created_at: string;
  updated_at: string;
}

export interface PackageVersionInfo {
  id: string;
  package_id: string;
  version: string;
  status: string;
  content_hash: string;
  risk: string;
  changelog: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  manifest?: Record<string, unknown>;
  graph?: { nodes: GraphNode[]; edges: GraphEdge[] };
  mermaid?: string;
}

export interface GraphNode {
  id: string;
  kind: string;
  slug: string;
  name: string;
}

export interface GraphEdge {
  from: string;
  to: string;
  relation: string;
}

export interface SecurityFinding {
  code: string;
  path: string;
  severity: 'INFO' | 'WARNING' | 'ERROR' | 'BLOCKER';
  message: string;
}

export interface InstallPreview {
  package: { id: string; name: string; type: string };
  version: string;
  version_id: string;
  resources_to_create: { kind: string; slug: string; name: string }[];
  dependencies: { type: string; package: string; resolved_version: string; optional: boolean }[];
  dependency_failures: { code: string; message: string }[];
  dependency_warnings: string[];
  required_credentials: { name: string; type: string; required: string }[];
  required_connectors: string[];
  required_tools: string[];
  required_skills: string[];
  required_models: string[];
  required_permissions: string[];
  security_warnings: SecurityFinding[];
  risk: string;
  policy_conflicts: string[];
  configuration_fields: ConfigField[];
  configuration_errors: string[];
  can_install: boolean;
  estimated_changes: { resources: number; dependencies: number; configuration_inputs: number };
}

export interface ConfigField {
  name: string;
  type: string;
  label: string;
  description: string;
  required: boolean;
  default?: unknown;
  options: string[];
  sensitive: boolean;
}

export interface Installation {
  id: string;
  package_id: string;
  package_slug: string;
  package_name: string;
  version: string;
  version_id: string;
  status: string;
  trust: string;
  official: boolean;
  update_available: string;
  error: string;
  installed_at: string | null;
  updated_at: string;
}

export interface SkillSummary {
  id: string;
  slug: string;
  name: string;
  description: string;
  status: string;
  trust: string;
  visibility: string;
  official: boolean;
  latest_version: string;
}

export interface PresetSummary {
  id: string;
  slug: string;
  name: string;
  kind: string;
  description: string;
  visibility: string;
  official: boolean;
  latest_version: string;
}

export interface CatalogEntry {
  package_id: string;
  slug: string;
  name: string;
  description: string;
  type: string;
  version: string;
  trust: string;
  visibility: string;
  official: boolean;
  categories: string[];
  tags: string[];
  author: string;
  risk: string;
  installed: boolean;
  updated_at: string;
  score: number;
}

export interface SecurityReportData {
  trust_level: string;
  official: boolean;
  risk: string;
  capabilities: string[];
  requires_approval: string[];
  network: string;
  sandbox: string;
  credential_references: { name: string; type: string }[];
  warnings: SecurityFinding[];
  policy: Record<string, unknown>;
}

function org(orgId: string, suffix: string): string {
  return `/organizations/${orgId}${suffix}`;
}

export const packagesApi = {
  list(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: PackageSummary[]; meta: { total_items: number } }>(
      org(orgId, '/packages'), params,
    );
  },
  get(orgId: string, id: string) {
    return api.get<PackageSummary>(org(orgId, `/packages/${id}`));
  },
  versions(orgId: string, id: string) {
    return api.get<{ data: PackageVersionInfo[] }>(org(orgId, `/packages/${id}/versions`));
  },
  versionDetail(orgId: string, id: string, version: string) {
    return api.get<PackageVersionInfo>(org(orgId, `/packages/${id}/versions/${version}`));
  },
  diff(orgId: string, id: string, v1: string, v2: string) {
    return api.get<Record<string, unknown>>(org(orgId, `/packages/${id}/versions/${v1}/diff/${v2}`));
  },
  security(orgId: string, id: string, version: string) {
    return api.get<SecurityReportData>(org(orgId, `/packages/${id}/versions/${version}/security`));
  },
  preview(orgId: string, id: string, version: string, values: Record<string, unknown> = {}) {
    return api.post<InstallPreview>(
      org(orgId, `/packages/${id}/versions/${version}/install-preview`), { values },
    );
  },
  install(orgId: string, id: string, version: string, values: Record<string, unknown> = {}) {
    return api.post<{ id: string; status: string; error: string }>(
      org(orgId, `/packages/${id}/versions/${version}/install`),
      { values, idempotency_key: `ui-${Date.now()}` },
    );
  },
  fork(orgId: string, id: string, slug: string, name: string) {
    return api.post<PackageSummary>(org(orgId, `/packages/${id}/fork`), { slug, name });
  },
  exportBundle(orgId: string, id: string, version: string) {
    return api.post<{ files: Record<string, string> }>(
      org(orgId, `/packages/${id}/versions/${version}/export`),
    );
  },
};

export const catalogApi = {
  search(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: CatalogEntry[]; meta: { total_items: number } }>(
      org(orgId, '/catalog/search'), params,
    );
  },
  categories(orgId: string) {
    return api.get<{ data: { slug: string; name: string; official: boolean }[] }>(
      org(orgId, '/catalog/categories'),
    );
  },
};

export const skillsApi = {
  list(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: SkillSummary[] }>(org(orgId, '/skills'), params);
  },
  get(orgId: string, id: string) {
    return api.get<SkillSummary>(org(orgId, `/skills/${id}`));
  },
  attach(orgId: string, id: string, target_type: 'agent' | 'workflow', target_id: string) {
    return api.post(org(orgId, `/skills/${id}/attach`), { target_type, target_id });
  },
};

export const presetsApi = {
  list(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: PresetSummary[] }>(org(orgId, '/presets'), params);
  },
};

export const installationsApi = {
  list(orgId: string, params?: Record<string, string | number | boolean | undefined>) {
    return api.get<{ data: Installation[] }>(org(orgId, '/installations'), params);
  },
  get(orgId: string, id: string) {
    return api.get(org(orgId, `/installations/${id}`));
  },
  planUpdate(orgId: string, id: string, to_version: string) {
    return api.post(org(orgId, `/installations/${id}/update-plan`), { to_version });
  },
  applyUpdate(orgId: string, id: string) {
    return api.post(org(orgId, `/installations/${id}/update`));
  },
  rollback(orgId: string, id: string) {
    return api.post(org(orgId, `/installations/${id}/rollback`));
  },
  uninstall(orgId: string, id: string) {
    return api.delete(org(orgId, `/installations/${id}`));
  },
};
