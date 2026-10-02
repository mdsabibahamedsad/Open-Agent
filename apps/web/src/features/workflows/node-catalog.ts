import {
  Bot,
  GitFork,
  GitMerge,
  Repeat,
  Shuffle,
  UserCheck,
  Globe,
  Wrench,
  Plug,
  Search,
  Clock,
  Play,
  Webhook,
  CalendarClock,
  Zap,
  Database,
  Filter,
  Braces,
  Variable,
  Sparkles,
  Workflow as WorkflowIcon,
  ListOrdered,
  Code2,
  FileSearch,
  FileCode2,
  FlaskConical,
  GitCommit,
  GitPullRequest,
  ShieldCheck,
  ScrollText,
  type LucideIcon,
} from 'lucide-react';
import type { TriggerType, WorkflowNode, WorkflowNodeType } from './types';

// Central node-definition registry (§8). Definitions describe *authoring*
// (palette, ports, config schema, docs); instances live in the definition.
// Sources beyond "builtin" (organization / marketplace / custom) plug in via
// registerNodeDefinition without touching the editor.

export type NodeCategory =
  | 'Triggers'
  | 'Logic'
  | 'Data'
  | 'AI'
  | 'Agents'
  | 'Tools'
  | 'HTTP'
  | 'Integrations'
  | 'Human'
  | 'Utilities'
  | 'Advanced';

export const NODE_CATEGORIES: NodeCategory[] = [
  'Triggers', 'Logic', 'Data', 'AI', 'Agents', 'Tools',
  'HTTP', 'Integrations', 'Human', 'Utilities', 'Advanced',
];

export type NodeSource = 'builtin' | 'organization' | 'marketplace' | 'custom';

export interface NodePort {
  /** Port key used as the edge label for multi-output nodes. */
  id: string;
  label: string;
  /** 'any' accepts everything in v1; typed for future execution. */
  dataType?: string;
  /** Max inbound edges (inputs) or outbound edges (outputs). */
  maxConnections?: number;
}

export interface TriggerMeta {
  type: TriggerType;
  label: string;
  description: string;
  icon: LucideIcon;
  version: number;
  configFields: ConfigField[];
}

export interface NodeMeta {
  type: WorkflowNodeType | string;
  /** Registry version of this definition (stored as node.type_version). */
  version: number;
  label: string;
  description: string;
  icon: LucideIcon;
  category: NodeCategory;
  source: NodeSource;
  /** Output port keys (geometry + edge labels). Single-port nodes use ['out']. */
  outputs: string[];
  hasInput: boolean;
  /** Inputs beyond the first require a merge node upstream. */
  fanIn?: boolean;
  terminal?: boolean;
  configFields: ConfigField[];
  defaultConfig: Record<string, unknown>;
  capabilities?: string[];
  documentationUrl?: string;
}

export interface ConfigField {
  key: string;
  label: string;
  type:
    | 'text'
    | 'textarea'
    | 'number'
    | 'boolean'
    | 'select'
    | 'keyvalue'
    | 'stringlist'
    | 'expression'
    | 'json'
    | 'credential';
  placeholder?: string;
  help?: string;
  required?: boolean;
  /** Never copied to clipboard or echoed in errors; only references stored. */
  sensitive?: boolean;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
}

export const TRIGGER_CATALOG: TriggerMeta[] = [
  {
    type: 'manual',
    label: 'Manual',
    description: 'Start runs by hand from the dashboard.',
    icon: Play,
    version: 1,
    configFields: [],
  },
  {
    type: 'webhook',
    label: 'Webhook',
    description: 'Start runs on incoming HTTP requests.',
    icon: Webhook,
    version: 1,
    configFields: [
      { key: 'path', label: 'Path', type: 'text', placeholder: '/hooks/support-triage', required: true, help: 'Path suffix the caller POSTs to.' },
      { key: 'secret', label: 'Shared secret', type: 'credential', placeholder: 'credential_id or {{secrets.hook}}', sensitive: true, help: 'Reference only — literal secrets are rejected by validation.' },
    ],
  },
  {
    type: 'schedule',
    label: 'Schedule',
    description: 'Start runs on a cron timetable.',
    icon: CalendarClock,
    version: 1,
    configFields: [
      { key: 'cron', label: 'Cron expression', type: 'text', placeholder: '0 9 * * MON-FRI', required: true },
      { key: 'timezone', label: 'Timezone', type: 'text', placeholder: 'UTC' },
    ],
  },
  {
    type: 'event',
    label: 'Event',
    description: 'Start runs when a platform event fires.',
    icon: Zap,
    version: 1,
    configFields: [
      { key: 'event', label: 'Event name', type: 'text', placeholder: 'ticket.created', required: true },
    ],
  },
];

const BUILTIN_NODES: NodeMeta[] = [
  {
    type: 'agent',
    version: 1,
    label: 'Agent',
    description: 'Delegate reasoning and action to an agent.',
    icon: Bot,
    category: 'Agents',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { agent_id: '' },
    configFields: [
      { key: 'agent_id', label: 'Agent ID', type: 'text', placeholder: 'Select or paste agent ID', required: true },
      { key: 'task', label: 'Task', type: 'expression', placeholder: 'What should the agent do with {{ticket}}?' },
      { key: 'max_steps', label: 'Max steps', type: 'number', min: 1, max: 100 },
    ],
    capabilities: ['reasoning', 'tools'],
  },
  {
    type: 'prompt',
    version: 1,
    label: 'AI Prompt',
    description: 'Single model call with system prompt.',
    icon: Sparkles,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { model: '', prompt: '' },
    configFields: [
      { key: 'model', label: 'Model', type: 'text', placeholder: 'Model id or router profile', required: true },
      { key: 'system', label: 'System prompt', type: 'textarea', placeholder: 'You are a helpful triage assistant.' },
      { key: 'prompt', label: 'Prompt', type: 'expression', placeholder: 'Summarize {{ticket}}', required: true },
      { key: 'max_tokens', label: 'Max tokens', type: 'number', min: 1, max: 128000 },
    ],
    capabilities: ['llm'],
  },
  {
    type: 'condition',
    version: 1,
    label: 'If / Condition',
    description: 'Branch on a boolean expression.',
    icon: GitFork,
    category: 'Logic',
    source: 'builtin',
    outputs: ['true', 'false'],
    hasInput: true,
    defaultConfig: { expression: '' },
    configFields: [
      { key: 'expression', label: 'Expression', type: 'expression', placeholder: "priority == 'high'", required: true, help: 'Evaluated against run variables by the execution engine.' },
    ],
  },
  {
    type: 'switch',
    version: 1,
    label: 'Switch / Router',
    description: 'Route to named branches by expression.',
    icon: ListOrdered,
    category: 'Logic',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { routes: [{ name: 'default', expression: 'true' }] },
    configFields: [
      { key: 'routes', label: 'Routes (JSON)', type: 'json', help: '[{"name": "vip", "expression": "tier == \'vip\'"}]. Edges use the route name as label.', required: true },
    ],
  },
  {
    type: 'merge',
    version: 1,
    label: 'Merge',
    description: 'Fan-in: join multiple branches.',
    icon: GitMerge,
    category: 'Logic',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    fanIn: true,
    defaultConfig: {},
    configFields: [
      { key: 'mode', label: 'Mode', type: 'select', options: [{ value: 'first', label: 'First arrival wins' }, { value: 'all', label: 'Wait for all' }], help: 'Authoring hint for the future engine.' },
    ],
  },
  {
    type: 'loop',
    version: 1,
    label: 'Loop',
    description: 'Iterate over a collection.',
    icon: Repeat,
    category: 'Logic',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { items: '', max_iterations: 100 },
    configFields: [
      { key: 'items', label: 'Collection expression', type: 'expression', placeholder: '{{tickets}}', required: true },
      { key: 'max_iterations', label: 'Max iterations', type: 'number', min: 1, max: 10000 },
    ],
  },
  {
    type: 'set',
    version: 1,
    label: 'Set',
    description: 'Assign static values to variables.',
    icon: Database,
    category: 'Data',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { values: {} },
    configFields: [
      { key: 'values', label: 'Values (JSON)', type: 'json', placeholder: '{"region": "eu"}', required: true },
    ],
  },
  {
    type: 'transform',
    version: 1,
    label: 'Transform',
    description: 'Map data without calling a model.',
    icon: Shuffle,
    category: 'Data',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { mapping: '' },
    configFields: [
      { key: 'mapping', label: 'Mapping (JSON)', type: 'expression', placeholder: '{"summary": "{{ticket.subject}}"}', required: true },
    ],
  },
  {
    type: 'filter',
    version: 1,
    label: 'Filter',
    description: 'Keep collection items matching a predicate.',
    icon: Filter,
    category: 'Data',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { items: '', predicate: '' },
    configFields: [
      { key: 'items', label: 'Collection expression', type: 'expression', placeholder: '{{tickets}}', required: true },
      { key: 'predicate', label: 'Predicate', type: 'expression', placeholder: "priority == 'high'", required: true },
    ],
  },
  {
    type: 'map',
    version: 1,
    label: 'Map',
    description: 'Transform each collection item.',
    icon: Braces,
    category: 'Data',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { items: '', expression: '' },
    configFields: [
      { key: 'items', label: 'Collection expression', type: 'expression', placeholder: '{{tickets}}', required: true },
      { key: 'expression', label: 'Per-item expression', type: 'expression', placeholder: '{{item.subject}}', required: true },
    ],
  },
  {
    type: 'variable',
    version: 1,
    label: 'Variable',
    description: 'Read or write a workflow variable.',
    icon: Variable,
    category: 'Utilities',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { mode: 'set', name: '' },
    configFields: [
      { key: 'mode', label: 'Mode', type: 'select', options: [{ value: 'set', label: 'Set' }, { value: 'get', label: 'Get' }], required: true },
      { key: 'name', label: 'Variable name', type: 'text', placeholder: 'ticket_id', required: true },
      { key: 'value', label: 'Value', type: 'expression', placeholder: '{{trigger.output.id}}', help: 'Required in set mode.' },
    ],
  },
  {
    type: 'approval',
    version: 1,
    label: 'Approval',
    description: 'Pause for human sign-off.',
    icon: UserCheck,
    category: 'Human',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    terminal: true,
    defaultConfig: { approvers: [] },
    configFields: [
      { key: 'approvers', label: 'Approvers', type: 'stringlist', help: 'One email or role per line.', required: true },
      { key: 'message', label: 'Message', type: 'textarea', placeholder: 'What needs review?' },
    ],
  },
  {
    type: 'webhook',
    version: 1,
    label: 'HTTP Request',
    description: 'Call an external HTTP endpoint.',
    icon: Globe,
    category: 'HTTP',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { url: '', method: 'POST' },
    configFields: [
      { key: 'url', label: 'URL', type: 'expression', placeholder: 'https://api.example.com/notify', required: true },
      { key: 'method', label: 'Method', type: 'select', options: [{ value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' }, { value: 'PUT', label: 'PUT' }, { value: 'PATCH', label: 'PATCH' }, { value: 'DELETE', label: 'DELETE' }] },
      { key: 'headers', label: 'Headers (JSON)', type: 'json', placeholder: '{"X-Team": "support"}' },
      { key: 'body', label: 'Body (JSON)', type: 'expression', placeholder: '{"ticket_id": "{{ticket_id}}"}' },
      { key: 'credential_id', label: 'Credential', type: 'credential', help: 'Reference id of a stored credential. Never paste secrets here.' },
    ],
  },
  {
    type: 'tool',
    version: 1,
    label: 'Tool',
    description: 'Invoke a registered tool.',
    icon: Wrench,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { tool_id: '' },
    configFields: [
      { key: 'tool_id', label: 'Tool ID', type: 'text', placeholder: 'Select or paste tool ID', required: true },
      { key: 'arguments', label: 'Arguments (JSON)', type: 'expression', placeholder: '{"query": "{{ticket.subject}}"}' },
      { key: 'credential_id', label: 'Credential', type: 'credential', help: 'Reference id of a stored credential.' },
    ],
  },
  {
    type: 'connector_action',
    version: 1,
    label: 'Connector Action',
    description: 'Invoke a connector action (policy → approval → execute → verify).',
    icon: Plug,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { action_id: '', connection_id: '', input: {} },
    configFields: [
      { key: 'action_id', label: 'Action', type: 'text', placeholder: 'github.create_issue', required: true, help: 'Search actions in Integrations → Catalog.' },
      { key: 'connection_id', label: 'Connection ID', type: 'text', placeholder: 'Paste connection ID (sharing-checked at runtime)' },
      { key: 'credential_id', label: 'Credential', type: 'credential', help: 'Reference id of a stored credential. Never paste secrets here.' },
      { key: 'input', label: 'Input (JSON)', type: 'expression', placeholder: '{"title": "{{ticket.subject}}"}' },
      { key: 'timeout_seconds', label: 'Timeout (s)', type: 'number', placeholder: '30' },
      { key: 'approval_id', label: 'Approval ID', type: 'text', placeholder: 'For pre-approved high-risk actions' },
    ],
  },
  {
    type: 'connector_trigger',
    version: 1,
    label: 'Connector Trigger',
    description: 'Start a run from a connector event (webhook/polling).',
    icon: Zap,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: false,
    defaultConfig: { trigger_id: '' },
    configFields: [
      { key: 'trigger_id', label: 'Trigger', type: 'text', placeholder: 'github.pull_request.opened', required: true },
      { key: 'connection_id', label: 'Connection ID', type: 'text', placeholder: 'Paste connection ID' },
      { key: 'filter', label: 'Filter (JSON)', type: 'json', placeholder: '{"repository": "acme/api"}' },
    ],
  },
  {
    type: 'connector_search',
    version: 1,
    label: 'Connector Search',
    description: 'Discover connector actions by keyword (compact results for agents).',
    icon: Search,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { query: '' },
    configFields: [
      { key: 'query', label: 'Query', type: 'text', placeholder: 'send Slack message', required: true },
      { key: 'limit', label: 'Limit', type: 'number', placeholder: '10' },
    ],
  },
  {
    type: 'connector_resource',
    version: 1,
    label: 'Connector Resource',
    description: 'Look up a normalized external resource.',
    icon: Database,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { kind: 'issue' },
    configFields: [
      { key: 'kind', label: 'Resource kind', type: 'text', placeholder: 'issue', required: true, help: 'user, message, file, repository, issue, pull_request, task, ticket, customer, invoice, order, calendar_event, document, database_row.' },
      { key: 'connector', label: 'Connector', type: 'text', placeholder: 'github' },
      { key: 'connection_id', label: 'Connection ID', type: 'text' },
      { key: 'lookup', label: 'Lookup (JSON)', type: 'json', placeholder: '{"id": "123"}' },
    ],
  },
  {
    type: 'verify',
    version: 1,
    label: 'Verify',
    description: 'Deterministic checks over inputs (status, files, schema, tests).',
    icon: ShieldCheck,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { checks: [] },
    configFields: [
      { key: 'checks', label: 'Checks (JSON)', type: 'json', placeholder: '[{"kind": "http_response", "params": {"expected_status": 200}}]', required: true, help: 'Each check: kind, target, params, required.' },
    ],
  },
  {
    type: 'evaluate',
    version: 1,
    label: 'Evaluate',
    description: 'Threshold quality decision over a score plus checks.',
    icon: FlaskConical,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { quality_threshold: 0.7 },
    configFields: [
      { key: 'score', label: 'Score', type: 'expression', placeholder: '{{nodes.agent.score}}', help: 'Numeric 0..1 or 0..100.' },
      { key: 'quality_threshold', label: 'Quality threshold', type: 'text', placeholder: '0.7' },
      { key: 'checks', label: 'Checks (JSON)', type: 'json', placeholder: '[]' },
    ],
  },
  {
    type: 'assert',
    version: 1,
    label: 'Assert',
    description: 'Hard success/failure condition. Fails the branch when unmet.',
    icon: ScrollText,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { conditions: [] },
    configFields: [
      { key: 'conditions', label: 'Conditions (JSON)', type: 'json', placeholder: '[{"kind": "json_schema", "params": {"schema": {}}}]', required: true },
    ],
  },
  {
    type: 'quality_gate',
    version: 1,
    label: 'Quality Gate',
    description: 'Built-in or literal gate: required checks plus thresholds.',
    icon: ShieldCheck,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { gate: 'workflow_success_gate' },
    configFields: [
      { key: 'gate', label: 'Built-in gate', type: 'select', options: [
        { value: 'code_build_gate', label: 'Code Build Gate' },
        { value: 'security_gate', label: 'Security Gate' },
        { value: 'research_quality_gate', label: 'Research Quality Gate' },
        { value: 'workflow_success_gate', label: 'Workflow Success Gate' },
        { value: 'browser_completion_gate', label: 'Browser Completion Gate' },
        { value: 'data_validation_gate', label: 'Data Validation Gate' },
        { value: 'production_deployment_gate', label: 'Production Deployment Gate' },
      ] },
      { key: 'check_targets', label: 'Check targets (JSON)', type: 'json', placeholder: '{"nodes_ok": {"agent": "succeeded"}}' },
      { key: 'score', label: 'Score', type: 'expression', placeholder: '{{nodes.evaluate.score}}' },
    ],
  },
  {
    type: 'retry',
    version: 1,
    label: 'Retry Until',
    description: 'Bounded retry counter. Fails safely when exhausted.',
    icon: Repeat,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { max_attempts: 3 },
    configFields: [
      { key: 'max_attempts', label: 'Max attempts (1..10)', type: 'text', placeholder: '3', required: true },
    ],
  },
  {
    type: 'correct',
    version: 1,
    label: 'Correct',
    description: 'Emit a bounded correction-plan descriptor for the API loop.',
    icon: Sparkles,
    category: 'AI',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { strategy: 'RETRY_SAME', max_correction_cycles: 3 },
    configFields: [
      { key: 'strategy', label: 'Strategy', type: 'select', options: [
        { value: 'RETRY_SAME', label: 'Retry same' },
        { value: 'RETRY_WITH_BACKOFF', label: 'Retry with backoff' },
        { value: 'RETRY_WITH_NEW_MODEL', label: 'Retry with new model' },
        { value: 'RETRY_WITH_NEW_TOOL', label: 'Retry with new tool' },
        { value: 'MODIFY_PARAMETERS', label: 'Modify parameters' },
        { value: 'REFINE_PROMPT', label: 'Refine prompt' },
        { value: 'EXPAND_CONTEXT', label: 'Expand context' },
        { value: 'REPLAN', label: 'Replan' },
        { value: 'ROLLBACK', label: 'Rollback' },
        { value: 'ASK_ANOTHER_AGENT', label: 'Ask another agent' },
        { value: 'REQUEST_HUMAN', label: 'Request human' },
        { value: 'STOP', label: 'Stop' },
      ] },
      { key: 'max_correction_cycles', label: 'Max cycles (1..10)', type: 'text', placeholder: '3' },
    ],
  },
  {
    type: 'delay',
    version: 1,
    label: 'Delay',
    description: 'Wait before continuing.',
    icon: Clock,
    category: 'Utilities',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { duration_seconds: 60 },
    configFields: [
      { key: 'duration_seconds', label: 'Duration (seconds)', type: 'number', min: 1, required: true },
    ],
  },
  {
    type: 'subworkflow',
    version: 1,
    label: 'Subworkflow',
    description: 'Reference another workflow (runs in a later phase).',
    icon: WorkflowIcon,
    category: 'Advanced',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { workflow_id: '' },
    configFields: [
      { key: 'workflow_id', label: 'Workflow ID', type: 'text', placeholder: 'Paste workflow id', required: true },
      { key: 'input', label: 'Input (JSON)', type: 'expression', placeholder: '{"ticket_id": "{{ticket_id}}"}' },
    ],
  },
  {
    type: 'code_agent',
    version: 1,
    label: 'Code Agent',
    description: 'Objective-driven coding task on an isolated workspace branch. Bounded steps; push stays approval-gated.',
    icon: Code2,
    category: 'Agents',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { objective: '', repository_id: '', max_steps: 50 },
    configFields: [
      { key: 'objective', label: 'Objective', type: 'expression', placeholder: 'Fix failing auth tests and open a PR', required: true, help: 'Coding goal, e.g. "Fix failing tests in the authentication module and create a PR."' },
      { key: 'repository_id', label: 'Repository ID', type: 'text', placeholder: 'Paste repository id', required: true },
      { key: 'branch_strategy', label: 'Branch strategy', type: 'text', placeholder: 'openagent/task/<task-id>' },
      { key: 'max_steps', label: 'Max steps', type: 'number', min: 1, max: 200 },
      { key: 'max_duration', label: 'Max duration (seconds)', type: 'number', min: 60 },
      { key: 'execution_policy', label: 'Execution policy (JSON)', type: 'json', placeholder: '{"profiles": ["TEST", "LINT"]}' },
      { key: 'review_policy', label: 'Review policy (JSON)', type: 'json' },
      { key: 'approval_policy', label: 'Approval policy (JSON)', type: 'json' },
    ],
    capabilities: ['code_execution', 'tool_execution'],
    documentationUrl: '/docs/code-agent/overview',
  },
  {
    type: 'code_search',
    version: 1,
    label: 'Code Search',
    description: 'Bounded text / regex / symbol / semantic search across a workspace.',
    icon: FileSearch,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { query: '', workspace_id: '' },
    configFields: [
      { key: 'query', label: 'Query', type: 'expression', placeholder: 'session validation', required: true },
      { key: 'workspace_id', label: 'Workspace ID', type: 'text', placeholder: 'Paste workspace id' },
      { key: 'repository_id', label: 'Repository ID', type: 'text', placeholder: 'Alternative to workspace id' },
      { key: 'regex', label: 'Regex mode', type: 'boolean' },
      { key: 'symbol', label: 'Symbol name', type: 'text', placeholder: 'validate_session' },
    ],
    capabilities: ['code_execution', 'read'],
    documentationUrl: '/docs/code-agent/search',
  },
  {
    type: 'code_read',
    version: 1,
    label: 'Code Read',
    description: 'Read a jailed workspace file or line range (content is untrusted data).',
    icon: FileCode2,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { path: '', workspace_id: '' },
    configFields: [
      { key: 'path', label: 'Path (workspace-relative)', type: 'text', placeholder: 'src/auth.py', required: true },
      { key: 'workspace_id', label: 'Workspace ID', type: 'text', placeholder: 'Paste workspace id' },
      { key: 'start', label: 'Start line', type: 'number', min: 1 },
      { key: 'end', label: 'End line', type: 'number', min: 1 },
    ],
    capabilities: ['code_execution', 'read'],
    documentationUrl: '/docs/code-agent/editing',
  },
  {
    type: 'code_patch',
    version: 1,
    label: 'Code Patch',
    description: 'Validate and apply a unified diff to a coding task workspace.',
    icon: ScrollText,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { task_id: '', diff: '' },
    configFields: [
      { key: 'task_id', label: 'Coding task ID', type: 'text', placeholder: 'Paste coding task id', required: true },
      { key: 'diff', label: 'Unified diff', type: 'textarea', placeholder: '--- a/src/auth.py\n+++ b/src/auth.py', required: true },
      { key: 'approved', label: 'Approved', type: 'boolean', help: 'Required for sensitive paths or high-risk changes.' },
    ],
    capabilities: ['code_execution', 'write'],
    documentationUrl: '/docs/code-agent/editing',
  },
  {
    type: 'code_test',
    version: 1,
    label: 'Code Test',
    description: 'Run tests through the TEST execution profile inside the sandbox boundary.',
    icon: FlaskConical,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { command: '', profile: 'TEST' },
    configFields: [
      { key: 'command', label: 'Command', type: 'expression', placeholder: 'pytest tests/unit -x -q', required: true },
      { key: 'profile', label: 'Profile', type: 'select', options: [
        { value: 'TEST', label: 'TEST' }, { value: 'LINT', label: 'LINT' },
        { value: 'TYPECHECK', label: 'TYPECHECK' }, { value: 'BUILD', label: 'BUILD' },
        { value: 'PACKAGE', label: 'PACKAGE' }, { value: 'MIGRATION', label: 'MIGRATION' },
      ] },
      { key: 'task_id', label: 'Coding task ID', type: 'text', placeholder: 'Paste coding task id' },
      { key: 'workspace_id', label: 'Workspace ID', type: 'text', placeholder: 'Paste workspace id' },
    ],
    capabilities: ['code_execution', 'test'],
    documentationUrl: '/docs/code-agent/testing',
  },
  {
    type: 'code_lint',
    version: 1,
    label: 'Code Lint',
    description: 'Run linters / type checks through gated execution profiles.',
    icon: ShieldCheck,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { command: '', profile: 'LINT' },
    configFields: [
      { key: 'command', label: 'Command', type: 'expression', placeholder: 'ruff check src/ && mypy src/', required: true },
      { key: 'profile', label: 'Profile', type: 'select', options: [
        { value: 'LINT', label: 'LINT' }, { value: 'TYPECHECK', label: 'TYPECHECK' },
        { value: 'TEST', label: 'TEST' }, { value: 'BUILD', label: 'BUILD' },
      ] },
      { key: 'task_id', label: 'Coding task ID', type: 'text', placeholder: 'Paste coding task id' },
      { key: 'workspace_id', label: 'Workspace ID', type: 'text', placeholder: 'Paste workspace id' },
    ],
    capabilities: ['code_execution', 'test'],
    documentationUrl: '/docs/code-agent/testing',
  },
  {
    type: 'code_review',
    version: 1,
    label: 'Code Review',
    description: 'Structured static review (correctness, security, tests) with severities.',
    icon: ScrollText,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { task_id: '' },
    configFields: [
      { key: 'task_id', label: 'Coding task ID', type: 'text', placeholder: 'Paste coding task id' },
      { key: 'diff', label: 'Unified diff (alternative)', type: 'textarea', placeholder: 'Review this diff instead of a task' },
    ],
    capabilities: ['code_execution', 'read'],
    documentationUrl: '/docs/code-agent/code-review',
  },
  {
    type: 'git_commit',
    version: 1,
    label: 'Git Commit',
    description: 'Secret-scanned, policy-gated commit on the task branch.',
    icon: GitCommit,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { task_id: '', message: '' },
    configFields: [
      { key: 'task_id', label: 'Coding task ID', type: 'text', placeholder: 'Paste coding task id', required: true },
      { key: 'message', label: 'Commit message', type: 'textarea', placeholder: 'fix(auth): validate session expiry', required: true },
    ],
    capabilities: ['code_execution', 'write'],
    documentationUrl: '/docs/code-agent/git',
  },
  {
    type: 'create_pr',
    version: 1,
    label: 'Create PR',
    description: 'Prepare (and optionally open) a pull-request draft. Never merges.',
    icon: GitPullRequest,
    category: 'Tools',
    source: 'builtin',
    outputs: ['out'],
    hasInput: true,
    defaultConfig: { task_id: '', title: '' },
    configFields: [
      { key: 'task_id', label: 'Coding task ID', type: 'text', placeholder: 'Paste coding task id', required: true },
      { key: 'title', label: 'PR title', type: 'text', placeholder: 'Fix session validation expiry', required: true },
      { key: 'summary', label: 'Summary', type: 'textarea', placeholder: 'What changed, tests, risks' },
      { key: 'open', label: 'Open on forge', type: 'boolean', help: 'Opens the PR remotely; never merges.' },
      { key: 'branch', label: 'Branch', type: 'text', placeholder: 'Defaults to the task branch', required: false },
    ],
    capabilities: ['code_execution', 'write'],
    documentationUrl: '/docs/code-agent/git',
  },
];

/** Registry: builtin first, then runtime-registered definitions. */
const customDefinitions = new Map<string, NodeMeta>();

/**
 * Register a node definition from organization / marketplace / custom code.
 * Throws on duplicate type — unregister first to replace.
 */
export function registerNodeDefinition(def: NodeMeta): void {
  const key = `${def.type}@${def.version}`;
  if (
    BUILTIN_NODES.some((n) => n.type === def.type && n.version === def.version) ||
    customDefinitions.has(key)
  ) {
    throw new Error(`Node definition already registered: ${key}`);
  }
  customDefinitions.set(key, def);
}

export function unregisterNodeDefinition(type: string, version: number): boolean {
  return customDefinitions.delete(`${type}@${version}`);
}

/** All definitions, builtin first. */
export function listNodeDefinitions(): NodeMeta[] {
  return [...BUILTIN_NODES, ...customDefinitions.values()];
}

/** Definitions grouped by category (extensible category set). */
export function definitionsByCategory(): { category: NodeCategory | string; items: NodeMeta[] }[] {
  const groups = new Map<string, NodeMeta[]>();
  for (const def of listNodeDefinitions()) {
    const list = groups.get(def.category) ?? [];
    list.push(def);
    groups.set(def.category, list);
  }
  const ordered = NODE_CATEGORIES.filter((c) => groups.has(c));
  const extra = [...groups.keys()].filter((c) => !NODE_CATEGORIES.includes(c as NodeCategory)).sort();
  return [...ordered, ...extra].map((category) => ({ category, items: groups.get(category)! }));
}

function findDefinition(type: string): NodeMeta | undefined {
  const customs = [...customDefinitions.values()].filter((d) => d.type === type);
  if (customs.length > 0) return customs.sort((a, b) => b.version - a.version)[0];
  return BUILTIN_NODES.find((n) => n.type === type);
}

/** Back-compat export: builtin catalog. */
export const NODE_CATALOG: NodeMeta[] = BUILTIN_NODES;

export function triggerMeta(type: TriggerType): TriggerMeta {
  const m = TRIGGER_CATALOG.find((t) => t.type === type);
  if (!m) throw new Error(`Unknown trigger type: ${type}`);
  return m;
}

export function nodeMeta(type: WorkflowNodeType | string): NodeMeta {
  const m = findDefinition(type);
  if (!m) throw new Error(`Unknown node type: ${type}`);
  return m;
}

/** Output ports for a node instance (switch routes become ports). */
export function outputPortsFor(meta: NodeMeta, node?: Pick<WorkflowNode, 'config'>): string[] {
  if (meta.type === 'switch' && node) {
    const routes = (node.config?.routes as { name?: unknown }[] | undefined) ?? [];
    const names = routes.map((r) => r?.name).filter((n): n is string => typeof n === 'string' && !!n);
    if (names.length > 0) return [...names, 'default'];
  }
  return meta.outputs;
}

/** Fields flagged sensitive (never copied, never echoed). */
export function sensitiveFields(meta: NodeMeta): string[] {
  return meta.configFields.filter((f) => f.sensitive).map((f) => f.key);
}
