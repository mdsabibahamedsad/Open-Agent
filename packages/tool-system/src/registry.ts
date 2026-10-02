import {
  ToolDefinition,
  ToolVersion,
  ToolProvider,
  ToolCategory,
  ToolCapability,
  ToolRiskLevel,
  ToolExecutionMode,
  ToolLifecycleStatus,
  ToolTrustLevel,
  ToolProviderType,
  ToolSearchFilters,
  ToolResolverResult,
  ToolPromptRepresentation,
} from './types';
import { OpenAgentLogger, createChildLogger } from '@openagent/logger';

const logger: OpenAgentLogger = createChildLogger({ module: 'tool-system:registry' });

export class ToolRegistry {
  private tools: Map<string, ToolDefinition> = new Map();
  private versions: Map<string, ToolVersion[]> = new Map();
  private providers: Map<string, ToolProvider> = new Map();
  private categoryIndex: Map<ToolCategory, Set<string>> = new Map();
  private capabilityIndex: Map<ToolCapability, Set<string>> = new Map();
  private riskIndex: Map<ToolRiskLevel, Set<string>> = new Map();
  private organizationIndex: Map<string, Set<string>> = new Map();
  private providerIndex: Map<string, Set<string>> = new Map();
  private tagIndex: Map<string, Set<string>> = new Map();

  register(tool: ToolDefinition): void {
    const key = this.getToolKey(tool.slug, tool.metadata.version);
    this.tools.set(key, tool);

    this.indexTool(tool);

    logger.info('Tool registered', {
      tool_id: tool.id,
      slug: tool.slug,
      version: tool.metadata.version,
      category: tool.metadata.category,
    });
  }

  registerVersion(version: ToolVersion): void {
    const toolVersions = this.versions.get(version.tool_id) || [];
    toolVersions.push(version);
    this.versions.set(version.tool_id, toolVersions);

    logger.info('Tool version registered', {
      tool_id: version.tool_id,
      version: version.version,
    });
  }

  registerProvider(provider: ToolProvider): void {
    this.providers.set(provider.id, provider);
    logger.info('Tool provider registered', { provider_id: provider.id, type: provider.provider_type });
  }

  unregister(slug: string, version: string): boolean {
    const key = this.getToolKey(slug, version);
    const tool = this.tools.get(key);
    if (!tool) return false;

    this.tools.delete(key);
    this.deindexTool(tool);

    logger.info('Tool unregistered', { tool_id: tool.id, slug, version });
    return true;
  }

  get(slug: string, version: string = '1.0'): ToolDefinition | undefined {
    return this.tools.get(this.getToolKey(slug, version));
  }

  getById(id: string): ToolDefinition | undefined {
    for (const tool of this.tools.values()) {
      if (tool.id === id) return tool;
    }
    return undefined;
  }

  getLatest(slug: string): ToolDefinition | undefined {
    const versions = Array.from(this.tools.values())
      .filter(t => t.slug === slug && t.status === 'ACTIVE')
      .sort((a, b) => this.compareVersions(b.metadata.version, a.metadata.version));
    return versions[0];
  }

  getVersions(toolId: string): ToolVersion[] {
    return this.versions.get(toolId) || [];
  }

  getLatestVersion(toolId: string): ToolVersion | undefined {
    const versions = this.getVersions(toolId);
    if (versions.length === 0) return undefined;
    return versions.sort((a, b) => this.compareVersions(b.version, a.version))[0];
  }

  listTools(filters?: ToolSearchFilters): ToolDefinition[] {
    let tools = Array.from(this.tools.values());

    if (filters) {
      tools = this.applyFilters(tools, filters);
    }

    return tools;
  }

  search(query: string, filters?: ToolSearchFilters): ToolDefinition[] {
    const lowerQuery = query.toLowerCase();
    let tools = Array.from(this.tools.values()).filter(
      t =>
        t.slug.toLowerCase().includes(lowerQuery) ||
        t.metadata.display_name.toLowerCase().includes(lowerQuery) ||
        t.metadata.description.toLowerCase().includes(lowerQuery) ||
        t.metadata.tags.some(tag => tag.toLowerCase().includes(lowerQuery))
    );

    if (filters) {
      tools = this.applyFilters(tools, filters);
    }

    return tools;
  }

  getCategories(): ToolCategory[] {
    return Array.from(this.categoryIndex.keys());
  }

  getCapabilities(): ToolCapability[] {
    return Array.from(this.capabilityIndex.keys());
  }

  getProviders(): ToolProvider[] {
    return Array.from(this.providers.values());
  }

  getProvider(id: string): ToolProvider | undefined {
    return this.providers.get(id);
  }

  resolveCompatibleVersion(toolId: string, requestedVersion: string): ToolVersion | undefined {
    const versions = this.getVersions(toolId);
    if (versions.length === 0) return undefined;

    const requested = this.parseVersion(requestedVersion);
    if (!requested) return this.getLatestVersion(toolId);

    const compatible = versions
      .filter(v => v.status === 'ACTIVE')
      .filter(v => this.isCompatible(this.parseVersion(v.version)!, requested))
      .sort((a, b) => this.compareVersions(b.version, a.version));

    return compatible[0];
  }

  checkCompatibility(toolId: string, version: string): boolean {
    const toolVersion = this.getVersions(toolId).find(v => v.version === version);
    if (!toolVersion) return false;
    return toolVersion.status === 'ACTIVE' || toolVersion.status === 'DEPRECATED';
  }

  toPromptRepresentation(tool: ToolDefinition): ToolPromptRepresentation {
    return {
      name: tool.slug,
      description: tool.metadata.description,
      input_schema: tool.input_schema,
      capabilities: tool.metadata.capabilities,
      risk_level: tool.metadata.risk_level,
    };
  }

  private getToolKey(slug: string, version: string): string {
    return `${slug}@${version}`;
  }

  private indexTool(tool: ToolDefinition): void {
    this.addToIndex(this.categoryIndex, tool.metadata.category, tool.id);
    this.addToIndex(this.organizationIndex, tool.organization_id || 'global', tool.id);
    this.addToIndex(this.providerIndex, tool.metadata.provider, tool.id);

    for (const cap of tool.metadata.capabilities) {
      this.addToIndex(this.capabilityIndex, cap, tool.id);
    }
    this.addToIndex(this.riskIndex, tool.metadata.risk_level, tool.id);

    for (const tag of tool.metadata.tags) {
      this.addToIndex(this.tagIndex, tag, tool.id);
    }
  }

  private deindexTool(tool: ToolDefinition): void {
    this.removeFromIndex(this.categoryIndex, tool.metadata.category, tool.id);
    this.removeFromIndex(this.organizationIndex, tool.organization_id || 'global', tool.id);
    this.removeFromIndex(this.providerIndex, tool.metadata.provider, tool.id);

    for (const cap of tool.metadata.capabilities) {
      this.removeFromIndex(this.capabilityIndex, cap, tool.id);
    }
    this.removeFromIndex(this.riskIndex, tool.metadata.risk_level, tool.id);

    for (const tag of tool.metadata.tags) {
      this.removeFromIndex(this.tagIndex, tag, tool.id);
    }
  }

  private addToIndex<K>(index: Map<K, Set<string>>, key: K, toolId: string): void {
    if (!index.has(key)) index.set(key, new Set());
    index.get(key)!.add(toolId);
  }

  private removeFromIndex<K>(index: Map<K, Set<string>>, key: K, toolId: string): void {
    const set = index.get(key);
    if (set) {
      set.delete(toolId);
      if (set.size === 0) index.delete(key);
    }
  }

  private applyFilters(tools: ToolDefinition[], filters: ToolSearchFilters): ToolDefinition[] {
    return tools.filter(tool => {
      if (filters.category && tool.metadata.category !== filters.category) return false;
      if (filters.capability && !tool.metadata.capabilities.includes(filters.capability)) return false;
      if (filters.risk_level && tool.metadata.risk_level !== filters.risk_level) return false;
      if (filters.organization_id && tool.organization_id !== filters.organization_id) return false;
      if (filters.provider && tool.metadata.provider !== filters.provider) return false;
      if (filters.status && tool.status !== filters.status) return false;
      if (filters.trust_level && tool.metadata.trust_level !== filters.trust_level) return false;
      if (filters.tags && filters.tags.length > 0) {
        if (!filters.tags.some(tag => tool.metadata.tags.includes(tag))) return false;
      }
      return true;
    });
  }

  private parseVersion(version: string): { major: number; minor: number; patch: number } | null {
    const match = version.match(/^v?(\d+)\.(\d+)\.(\d+)$/);
    if (!match) return null;
    return { major: parseInt(match[1]), minor: parseInt(match[2]), patch: parseInt(match[3]) };
  }

  private compareVersions(a: string, b: string): number {
    const va = this.parseVersion(a);
    const vb = this.parseVersion(b);
    if (!va || !vb) return a.localeCompare(b);
    if (va.major !== vb.major) return va.major - vb.major;
    if (va.minor !== vb.minor) return va.minor - vb.minor;
    return va.patch - vb.patch;
  }

  private isCompatible(current: { major: number; minor: number; patch: number }, requested: { major: number; minor: number; patch: number }): boolean {
    if (current.major !== requested.major) return false;
    if (current.minor < requested.minor) return false;
    if (current.minor === requested.minor && current.patch < requested.patch) return false;
    return true;
  }
}

export const toolRegistry = new ToolRegistry();