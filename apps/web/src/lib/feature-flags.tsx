'use client';

import { createContext, useContext, useMemo } from 'react';
import type { FeatureFlags } from '@/types';

const DEFAULT_FLAGS: FeatureFlags = {
  agent_runtime: false,
  workflow_builder: true,
  marketplace: true,
  browser_agent: false,
  coding_agent: false,
  mcp: false,
  cloud: false,
  billing: false,
  enterprise: false,
  advanced_workflow_groups: false,
  workflow_collaboration: false,
  workflow_templates: true,
  custom_nodes: false,
};

function readEnvFlags(): Partial<FeatureFlags> {
  const get = (k: string): boolean | undefined => {
    const v = process.env[k];
    if (v === '1' || v === 'true') return true;
    if (v === '0' || v === 'false') return false;
    return undefined;
  };
  return {
    agent_runtime: get('NEXT_PUBLIC_FF_AGENT_RUNTIME'),
    workflow_builder: get('NEXT_PUBLIC_FF_WORKFLOW_BUILDER'),
    marketplace: get('NEXT_PUBLIC_FF_MARKETPLACE'),
    browser_agent: get('NEXT_PUBLIC_FF_BROWSER_AGENT'),
    coding_agent: get('NEXT_PUBLIC_FF_CODING_AGENT'),
    mcp: get('NEXT_PUBLIC_FF_MCP'),
    cloud: get('NEXT_PUBLIC_FF_CLOUD'),
    billing: get('NEXT_PUBLIC_FF_BILLING'),
    enterprise: get('NEXT_PUBLIC_FF_ENTERPRISE'),
    advanced_workflow_groups: get('NEXT_PUBLIC_FF_ADVANCED_WORKFLOW_GROUPS'),
    workflow_collaboration: get('NEXT_PUBLIC_FF_WORKFLOW_COLLABORATION'),
    workflow_templates: get('NEXT_PUBLIC_FF_WORKFLOW_TEMPLATES'),
    custom_nodes: get('NEXT_PUBLIC_FF_CUSTOM_NODES'),
  } as Partial<FeatureFlags>;
}

const FeatureFlagContext = createContext<FeatureFlags>(DEFAULT_FLAGS);

export function FeatureFlagProvider({ children }: { children: React.ReactNode }) {
  const flags = useMemo<FeatureFlags>(() => {
    const env = readEnvFlags();
    const merged: FeatureFlags = { ...DEFAULT_FLAGS };
    for (const [k, v] of Object.entries(env)) {
      if (typeof v === 'boolean') (merged as unknown as Record<string, boolean>)[k] = v;
    }
    return merged;
  }, []);
  return <FeatureFlagContext.Provider value={flags}>{children}</FeatureFlagContext.Provider>;
}

export function useFeatureFlags(): FeatureFlags {
  return useContext(FeatureFlagContext);
}

export function useFeature(flag: keyof FeatureFlags): boolean {
  return useContext(FeatureFlagContext)[flag];
}
