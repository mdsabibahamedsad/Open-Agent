# Agent Contracts

## Purpose

A contract is a structured work agreement: objective, responsibilities,
inputs, expected outputs, capabilities, constraints, required permissions,
budget, deadline, quality requirements, acceptance criteria, escalation
conditions. Structured data — never only prose.

## What contracts are not

Contracts grant nothing. Permissions come from RBAC, policy, credential
authorization, and tool policy. Task ownership (`owner_agent`,
`supervising_agent`) assigns responsibility without opening private
resources.

## Validation

Objective, responsibilities, expected outputs, and acceptance criteria are
required; `max_revisions` bounded (0–10); secret-like keys rejected.

## Task ownership

Every active task has an owner; supervision is recorded via relationships
(`manages`, `can_review`). Reassignment and worker replacement preserve
attempt history and transfer only authorized context.
