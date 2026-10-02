// Tests for @openagent/extension-sdk builders.
import { describe, expect, it } from 'vitest';
import {
  defineAgent,
  defineConnector,
  defineEvaluator,
  defineMCPServer,
  defineSkill,
  defineTool,
  defineWorkflowNode,
  manifestFor,
} from './index';

describe('extension-sdk', () => {
  it('defineAgent compiles with defaults', () => {
    const agent = defineAgent({ name: 'research', instructions: 'Research things.' });
    expect(agent.kind).toBe('agent');
    expect(agent.model).toEqual({ alias: 'smart' });
    expect(agent.tools).toEqual([]);
  });

  it('defineAgent rejects empty instructions', () => {
    expect(() => defineAgent({ name: 'x', instructions: '  ' })).toThrow();
  });

  it('defineTool requires schema + executor', () => {
    const tool = defineTool({
      name: 'calc', description: 'Calculates.',
      inputSchema: { type: 'object' },
      execute: async () => ({ ok: true }),
    });
    expect(tool.riskLevel).toBe('low');
    expect(() => defineTool({ name: '', description: 'd', inputSchema: {}, execute: async () => 1 })).toThrow();
  });

  it('defineWorkflowNode requires type', () => {
    expect(() => defineWorkflowNode({ type: '', execute: async () => ({}) })).toThrow();
    const node = defineWorkflowNode({ type: 'example.transform', execute: async (ctx) => ({ out: ctx.inputs }) });
    expect(node.inputs).toEqual([]);
  });

  it('defineConnector requires actions', () => {
    expect(() => defineConnector({ slug: 'x', displayName: 'X', actions: [] })).toThrow();
  });

  it('defineMCPServer defaults transport', () => {
    const server = defineMCPServer({
      name: 'demo',
      tools: [{ name: 'ping', description: 'ping', run: async () => 'pong' }],
    });
    expect(server.transport).toBe('http');
  });

  it('defineSkill refuses policy-override declarations', () => {
    expect(() => defineSkill({
      name: 's', description: 'd', instructions: 'do',
      policies: ['bypass approval policy'],
    })).toThrow();
  });

  it('defineEvaluator builds verdict contract', async () => {
    const evaluator = defineEvaluator({
      name: 'q', evaluate: () => ({ score: 0.9, passed: true }),
    });
    expect(await evaluator.evaluate({})).toEqual({ score: 0.9, passed: true });
  });

  it('manifestFor infers extension types', () => {
    const agent = defineAgent({ name: 'a', instructions: 'i' });
    const manifest = manifestFor(agent, {
      name: 'my-agent', version: '1.0.0', description: 'd', author: { name: 'Acme' },
    });
    expect(manifest.type).toBe('agent');
    expect(manifest.compatibility?.extension_api).toBe('1.x');
  });
});
