import {
  ToolDefinition,
  ToolExecutionContext,
  ToolRiskLevel,
  ToolCapability,
} from "./types";
import { OpenAgentLogger, createChildLogger } from "@openagent/logger";

const logger: OpenAgentLogger = createChildLogger({
  module: "tool-system:risk",
});

export interface RiskEvaluationResult {
  risk_level: ToolRiskLevel;
  blocked: boolean;
  requires_approval: boolean;
  reason?: string;
  factors: RiskFactor[];
}

export interface RiskFactor {
  factor: string;
  impact: "INCREASE" | "DECREASE" | "NEUTRAL";
  description: string;
}

export interface RiskRule {
  id: string;
  name: string;
  condition: (tool: ToolDefinition, context: ToolExecutionContext) => boolean;
  impact: "INCREASE" | "DECREASE";
  risk_level_change: number;
  description: string;
}

export class RiskEngine {
  private rules: RiskRule[] = [];
  private riskThresholds: Map<
    ToolRiskLevel,
    { blocked: boolean; approval: boolean }
  > = new Map();

  constructor() {
    this.initializeDefaultRules();
    this.initializeDefaultThresholds();
  }

  private initializeDefaultRules(): void {
    this.rules = [
      {
        id: "critical-capability",
        name: "Critical Capability",
        condition: (tool) =>
          tool.metadata.capabilities.includes("process_execution") ||
          tool.metadata.capabilities.includes("system_control") ||
          tool.metadata.capabilities.includes("code_execution"),
        impact: "INCREASE",
        risk_level_change: 2,
        description:
          "Tool has critical capabilities (process execution, system control, code execution)",
      },
      {
        id: "high-capability",
        name: "High-Risk Capability",
        condition: (tool) =>
          tool.metadata.capabilities.includes("financial_action") ||
          tool.metadata.capabilities.includes("credential_access") ||
          tool.metadata.capabilities.includes("database_access") ||
          tool.metadata.capabilities.includes("browser_control"),
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool has high-risk capabilities",
      },
      {
        id: "network-access",
        name: "Network Access",
        condition: (tool) =>
          tool.metadata.capabilities.includes("network") ||
          tool.metadata.capabilities.includes("external_api"),
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool has network access capabilities",
      },
      {
        id: "write-capability",
        name: "Write Capability",
        condition: (tool) =>
          tool.metadata.capabilities.includes("write") ||
          tool.metadata.capabilities.includes("delete") ||
          tool.metadata.capabilities.includes("email_send") ||
          tool.metadata.capabilities.includes("message_send"),
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool can modify external state",
      },
      {
        id: "untrusted-provider",
        name: "Untrusted Provider",
        condition: (tool) =>
          tool.metadata.trust_level === "UNTRUSTED" ||
          tool.metadata.trust_level === "COMMUNITY",
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool is from an untrusted or community provider",
      },
      {
        id: "verified-provider",
        name: "Verified Provider",
        condition: (tool) =>
          tool.metadata.trust_level === "VERIFIED" ||
          tool.metadata.trust_level === "CORE",
        impact: "DECREASE",
        risk_level_change: 1,
        description: "Tool is from a verified or core provider",
      },
      {
        id: "readonly-tool",
        name: "Read-Only Tool",
        condition: (tool) =>
          tool.metadata.capabilities.length === 1 &&
          tool.metadata.capabilities[0] === "read",
        impact: "DECREASE",
        risk_level_change: 1,
        description: "Tool is read-only",
      },
      {
        id: "async-execution",
        name: "Async Execution",
        condition: (tool) =>
          tool.metadata.execution_mode === "ASYNC" ||
          tool.metadata.execution_mode === "BACKGROUND",
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool runs asynchronously or in background",
      },
      {
        id: "streaming-tool",
        name: "Streaming Tool",
        condition: (tool) => tool.metadata.execution_mode === "STREAMING",
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool produces streaming output",
      },
      {
        id: "no-schema",
        name: "Missing Output Schema",
        condition: (tool) => !tool.output_schema,
        impact: "INCREASE",
        risk_level_change: 1,
        description: "Tool does not define an output schema",
      },
    ];
  }

  private initializeDefaultThresholds(): void {
    this.riskThresholds.set("LOW", { blocked: false, approval: false });
    this.riskThresholds.set("MEDIUM", { blocked: false, approval: false });
    this.riskThresholds.set("HIGH", { blocked: false, approval: true });
    this.riskThresholds.set("CRITICAL", { blocked: true, approval: true });
  }

  addRule(rule: RiskRule): void {
    this.rules.push(rule);
  }

  removeRule(ruleId: string): boolean {
    const index = this.rules.findIndex((r) => r.id === ruleId);
    if (index >= 0) {
      this.rules.splice(index, 1);
      return true;
    }
    return false;
  }

  setThreshold(
    riskLevel: ToolRiskLevel,
    blocked: boolean,
    approval: boolean,
  ): void {
    this.riskThresholds.set(riskLevel, { blocked, approval });
  }

  async evaluate(
    tool: ToolDefinition,
    context: ToolExecutionContext,
  ): Promise<RiskEvaluationResult> {
    const factors: RiskFactor[] = [];
    let calculatedRiskScore = this.getBaseRiskScore(tool.metadata.risk_level);

    for (const rule of this.rules) {
      if (rule.condition(tool, context)) {
        factors.push({
          factor: rule.id,
          impact: rule.impact,
          description: rule.description,
        });

        if (rule.impact === "INCREASE") {
          calculatedRiskScore += rule.risk_level_change;
        } else {
          calculatedRiskScore -= rule.risk_level_change;
        }
      }
    }

    calculatedRiskScore = Math.max(0, Math.min(3, calculatedRiskScore));
    const finalRiskLevel = this.scoreToRiskLevel(calculatedRiskScore);

    const thresholds = this.riskThresholds.get(finalRiskLevel) || {
      blocked: false,
      approval: false,
    };

    logger.debug("Risk evaluation completed", {
      tool_id: tool.id,
      base_risk: tool.metadata.risk_level,
      final_risk: finalRiskLevel,
      factors: factors.length,
      blocked: thresholds.blocked,
      requires_approval: thresholds.approval,
    });

    return {
      risk_level: finalRiskLevel,
      blocked: thresholds.blocked,
      requires_approval: thresholds.approval,
      reason: thresholds.blocked
        ? `Risk level ${finalRiskLevel} is blocked by policy`
        : thresholds.approval
          ? `Risk level ${finalRiskLevel} requires approval`
          : undefined,
      factors,
    };
  }

  private getBaseRiskScore(riskLevel: ToolRiskLevel): number {
    const scores: Record<ToolRiskLevel, number> = {
      LOW: 0,
      MEDIUM: 1,
      HIGH: 2,
      CRITICAL: 3,
    };
    return scores[riskLevel];
  }

  private scoreToRiskLevel(score: number): ToolRiskLevel {
    if (score >= 3) return "CRITICAL";
    if (score >= 2) return "HIGH";
    if (score >= 1) return "MEDIUM";
    return "LOW";
  }

  getRules(): RiskRule[] {
    return [...this.rules];
  }

  getThresholds(): Map<ToolRiskLevel, { blocked: boolean; approval: boolean }> {
    return new Map(this.riskThresholds);
  }
}
