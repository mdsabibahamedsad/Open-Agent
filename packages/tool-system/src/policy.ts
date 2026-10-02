import {
  ToolDefinition,
  ToolExecutionContext,
  ToolPolicy,
  ToolCategory,
  ToolCapability,
  ToolRiskLevel,
  ToolCategoryValues,
  ToolCapabilityValues,
} from "./types";
import { OpenAgentLogger, createChildLogger } from "@openagent/logger";

const logger: OpenAgentLogger = createChildLogger({
  module: "tool-system:policy",
});

export interface PolicyEvaluationResult {
  allowed: boolean;
  requires_approval: boolean;
  reason?: string;
  matched_policies: string[];
}

export class PolicyEngine {
  private globalPolicy: ToolPolicy;
  private organizationPolicies: Map<string, ToolPolicy> = new Map();
  private teamPolicies: Map<string, ToolPolicy> = new Map();
  private agentPolicies: Map<string, ToolPolicy> = new Map();
  private workflowPolicies: Map<string, ToolPolicy> = new Map();

  constructor(globalPolicy: ToolPolicy) {
    this.globalPolicy = globalPolicy;
  }

  setOrganizationPolicy(orgId: string, policy: ToolPolicy): void {
    this.organizationPolicies.set(orgId, policy);
  }

  setTeamPolicy(teamId: string, policy: ToolPolicy): void {
    this.teamPolicies.set(teamId, policy);
  }

  setAgentPolicy(agentId: string, policy: ToolPolicy): void {
    this.agentPolicies.set(agentId, policy);
  }

  setWorkflowPolicy(workflowId: string, policy: ToolPolicy): void {
    this.workflowPolicies.set(workflowId, policy);
  }

  async evaluate(
    tool: ToolDefinition,
    context: ToolExecutionContext,
  ): Promise<PolicyEvaluationResult> {
    const policies = this.getApplicablePolicies(context);
    const matchedPolicies: string[] = [];

    for (const policy of policies) {
      matchedPolicies.push(policy.source);
      const result = this.evaluatePolicy(tool, policy, context);
      if (!result.allowed) {
        return { ...result, matched_policies: matchedPolicies };
      }
      if (result.requires_approval) {
        return { ...result, matched_policies: matchedPolicies };
      }
    }

    return {
      allowed: true,
      requires_approval: false,
      matched_policies: matchedPolicies,
    };
  }

  private getApplicablePolicies(
    context: ToolExecutionContext,
  ): Array<ToolPolicy & { source: string }> {
    const policies: Array<ToolPolicy & { source: string }> = [
      { ...this.globalPolicy, source: "global" },
    ];

    if (context.organization_id) {
      const orgPolicy = this.organizationPolicies.get(context.organization_id);
      if (orgPolicy)
        policies.push({
          ...orgPolicy,
          source: `organization:${context.organization_id}`,
        });
    }

    if (context.metadata.team_id) {
      const teamPolicy = this.teamPolicies.get(
        context.metadata.team_id as string,
      );
      if (teamPolicy)
        policies.push({
          ...teamPolicy,
          source: `team:${context.metadata.team_id}`,
        });
    }

    if (context.agent_id) {
      const agentPolicy = this.agentPolicies.get(context.agent_id);
      if (agentPolicy)
        policies.push({ ...agentPolicy, source: `agent:${context.agent_id}` });
    }

    if (context.workflow_id) {
      const workflowPolicy = this.workflowPolicies.get(context.workflow_id);
      if (workflowPolicy)
        policies.push({
          ...workflowPolicy,
          source: `workflow:${context.workflow_id}`,
        });
    }

    return policies;
  }

  private evaluatePolicy(
    tool: ToolDefinition,
    policy: ToolPolicy,
    context: ToolExecutionContext,
  ): PolicyEvaluationResult {
    if (
      policy.blocked_tools.includes(tool.id) ||
      policy.blocked_tools.includes(tool.slug)
    ) {
      return {
        allowed: false,
        requires_approval: false,
        reason: `Tool ${tool.slug} is explicitly blocked`,
        matched_policies: [],
      };
    }

    if (
      policy.allowed_tools.length > 0 &&
      !policy.allowed_tools.includes(tool.id) &&
      !policy.allowed_tools.includes(tool.slug)
    ) {
      return {
        allowed: false,
        requires_approval: false,
        reason: `Tool ${tool.slug} is not in allowed list`,
        matched_policies: [],
      };
    }

    if (policy.blocked_categories.includes(tool.metadata.category)) {
      return {
        allowed: false,
        requires_approval: false,
        reason: `Category ${tool.metadata.category} is blocked`,
        matched_policies: [],
      };
    }

    if (
      policy.allowed_categories.length > 0 &&
      !policy.allowed_categories.includes(tool.metadata.category)
    ) {
      return {
        allowed: false,
        requires_approval: false,
        reason: `Category ${tool.metadata.category} is not allowed`,
        matched_policies: [],
      };
    }

    if (
      policy.max_risk_level &&
      this.compareRiskLevel(tool.metadata.risk_level, policy.max_risk_level) > 0
    ) {
      return {
        allowed: false,
        requires_approval: false,
        reason: `Tool risk level ${tool.metadata.risk_level} exceeds maximum ${policy.max_risk_level}`,
        matched_policies: [],
      };
    }

    if (
      policy.allowed_risk_levels.length > 0 &&
      !policy.allowed_risk_levels.includes(tool.metadata.risk_level)
    ) {
      return {
        allowed: false,
        requires_approval: false,
        reason: `Risk level ${tool.metadata.risk_level} is not allowed`,
        matched_policies: [],
      };
    }

    for (const cap of tool.metadata.capabilities) {
      if (policy.blocked_capabilities.includes(cap)) {
        return {
          allowed: false,
          requires_approval: false,
          reason: `Capability ${cap} is blocked`,
          matched_policies: [],
        };
      }
    }

    if (policy.allowed_capabilities.length > 0) {
      const hasAllowedCap = tool.metadata.capabilities.some((c) =>
        policy.allowed_capabilities.includes(c),
      );
      if (!hasAllowedCap) {
        return {
          allowed: false,
          requires_approval: false,
          reason: `No allowed capabilities found`,
          matched_policies: [],
        };
      }
    }

    const requiresApproval =
      policy.approval_required[tool.id] === true ||
      policy.approval_required[tool.slug] === true ||
      policy.approval_required[tool.metadata.category] === true;

    if (requiresApproval) {
      return {
        allowed: true,
        requires_approval: true,
        reason: "Tool execution requires approval",
        matched_policies: [],
      };
    }

    return { allowed: true, requires_approval: false, matched_policies: [] };
  }

  private compareRiskLevel(a: ToolRiskLevel, b: ToolRiskLevel): number {
    const levels: ToolRiskLevel[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
    return levels.indexOf(a) - levels.indexOf(b);
  }

  getEffectivePolicy(context: ToolExecutionContext): ToolPolicy {
    const policies = this.getApplicablePolicies(context);
    return this.mergePolicies(policies.map((p) => ({ ...p, source: "" })));
  }

  private mergePolicies(policies: ToolPolicy[]): ToolPolicy {
    if (policies.length === 0) return this.getDefaultPolicy();

    return policies.reduce((merged, policy) => ({
      allowed_tools: [
        ...new Set([...merged.allowed_tools, ...policy.allowed_tools]),
      ],
      blocked_tools: [
        ...new Set([...merged.blocked_tools, ...policy.blocked_tools]),
      ],
      allowed_categories: [
        ...new Set([
          ...merged.allowed_categories,
          ...policy.allowed_categories,
        ]),
      ],
      blocked_categories: [
        ...new Set([
          ...merged.blocked_categories,
          ...policy.blocked_categories,
        ]),
      ],
      allowed_risk_levels: [
        ...new Set([
          ...merged.allowed_risk_levels,
          ...policy.allowed_risk_levels,
        ]),
      ],
      max_risk_level: this.getMostRestrictiveRiskLevel(
        merged.max_risk_level,
        policy.max_risk_level,
      ),
      allowed_capabilities: [
        ...new Set([
          ...merged.allowed_capabilities,
          ...policy.allowed_capabilities,
        ]),
      ],
      blocked_capabilities: [
        ...new Set([
          ...merged.blocked_capabilities,
          ...policy.blocked_capabilities,
        ]),
      ],
      allowed_domains: [
        ...new Set([...merged.allowed_domains, ...policy.allowed_domains]),
      ],
      blocked_domains: [
        ...new Set([...merged.blocked_domains, ...policy.blocked_domains]),
      ],
      allowed_organizations: [
        ...new Set([
          ...merged.allowed_organizations,
          ...policy.allowed_organizations,
        ]),
      ],
      approval_required: {
        ...merged.approval_required,
        ...policy.approval_required,
      },
      execution_limits: this.mergeExecutionLimits(
        merged.execution_limits,
        policy.execution_limits,
      ),
    }));
  }

  private getMostRestrictiveRiskLevel(
    a?: ToolRiskLevel,
    b?: ToolRiskLevel,
  ): ToolRiskLevel | undefined {
    if (!a) return b;
    if (!b) return a;
    const levels: ToolRiskLevel[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
    return levels.indexOf(a) < levels.indexOf(b) ? a : b;
  }

  private mergeExecutionLimits(
    a: ToolPolicy["execution_limits"],
    b: ToolPolicy["execution_limits"],
  ): ToolPolicy["execution_limits"] {
    return {
      max_concurrent_executions: Math.min(
        a.max_concurrent_executions,
        b.max_concurrent_executions,
      ),
      max_execution_time_seconds: Math.min(
        a.max_execution_time_seconds,
        b.max_execution_time_seconds,
      ),
      max_output_size_bytes: Math.min(
        a.max_output_size_bytes,
        b.max_output_size_bytes,
      ),
      max_input_size_bytes: Math.min(
        a.max_input_size_bytes,
        b.max_input_size_bytes,
      ),
      daily_execution_limit: Math.min(
        a.daily_execution_limit,
        b.daily_execution_limit,
      ),
    };
  }

  private getDefaultPolicy(): ToolPolicy {
    return {
      allowed_tools: [],
      blocked_tools: [],
      allowed_categories: ToolCategoryValues,
      blocked_categories: [],
      allowed_risk_levels: ["LOW", "MEDIUM"],
      max_risk_level: "MEDIUM",
      allowed_capabilities: ToolCapabilityValues,
      blocked_capabilities: [],
      allowed_domains: [],
      blocked_domains: [],
      allowed_organizations: [],
      approval_required: {},
      execution_limits: {
        max_concurrent_executions: 10,
        max_execution_time_seconds: 300,
        max_output_size_bytes: 10 * 1024 * 1024,
        max_input_size_bytes: 10 * 1024 * 1024,
        daily_execution_limit: 10000,
      },
    };
  }
}

export function createDefaultGlobalPolicy(): ToolPolicy {
  return {
    allowed_tools: [],
    blocked_tools: ["shell.exec", "filesystem.delete", "code.execute"],
    allowed_categories: ToolCategoryValues.filter(
      (c) => c !== "shell" && c !== "system",
    ),
    blocked_categories: ["shell", "system"],
    allowed_risk_levels: ["LOW", "MEDIUM"],
    max_risk_level: "HIGH",
    allowed_capabilities: ToolCapabilityValues.filter(
      (c) =>
        c !== "process_execution" &&
        c !== "system_control" &&
        c !== "code_execution",
    ),
    blocked_capabilities: [
      "process_execution",
      "system_control",
      "code_execution",
    ],
    allowed_domains: [],
    blocked_domains: [
      "localhost",
      "127.0.0.1",
      "10.",
      "192.168.",
      "172.16.",
      "169.254.",
    ],
    allowed_organizations: [],
    approval_required: {
      "email.send": true,
      "crm.update": true,
      "finance.payment": true,
    },
    execution_limits: {
      max_concurrent_executions: 10,
      max_execution_time_seconds: 300,
      max_output_size_bytes: 10 * 1024 * 1024,
      max_input_size_bytes: 10 * 1024 * 1024,
      daily_execution_limit: 10000,
    },
  };
}
