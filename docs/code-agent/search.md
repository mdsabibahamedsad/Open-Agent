# Code Search — Layered Search + Repository Index

Never load whole repositories into model context. Use the layered engine:

```bash
POST /api/v1/code/search   # {workspace_id, query, mode, symbol?, top_k?}
```

| Mode | Backend | Use for |
|---|---|---|
| `text` | indexed exact search (ripgrep-equivalent) | locating strings, errors |
| `regex` | bounded regex over workspace | patterns |
| `symbol` | `class/function/method/interface/type/constant/variable/module` index | definitions |
| `references` | reference index | callers, usages, imports |
| `semantic` | embedding-backed code index | concept search ("session validation") |

## Index pipeline

```text
Repository → File discovery → Ignore rules (.gitignore, excludes, vendor,
node_modules, build output) → Language detection → Parsing → Symbol
extraction → Dependency extraction → Chunking → Index
```

Tables (`016_add_code_agent`): `code_files`, `code_symbols`,
`code_references`, `code_dependencies`, `code_chunks`, `code_embeddings`,
`code_index_jobs`. Code embeddings live in **dedicated** tables — never in
ordinary user-memory tables.

## Incremental indexing

Only `created / modified / deleted / renamed` files are re-indexed after an
edit (`reindex_paths`); full re-index is a fallback, not the default.

## Language support

Python, TypeScript/JavaScript, Java, Go, Rust, C#, C/C++, SQL, HTML, CSS,
JSON, YAML, Markdown via the `CodeParser` protocol (`parse / symbols /
references`) with graceful degradation per language. Tree-sitter-style
parsers sit behind the abstraction — the platform is not coupled to one
implementation.

## Context builder

`build_task_context` assembles a bounded package per objective: relevant
files, symbols, related tests, dependencies, callers/callees, config, docs,
git history, recent changes — with `max context size` enforced. Repository
content is labeled untrusted (`label_untrusted_code`) all the way down.
