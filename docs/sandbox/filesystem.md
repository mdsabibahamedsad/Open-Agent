# Sandbox — Filesystem Isolation

Container view:

```text
/
├── app/          # runtime (read-only)
├── workspace/    # mounted task checkout (RO or RW per profile)
├── tmp/          # tmpfs rw,noexec,nosuid (when allowed)
├── artifacts/    # explicit export staging
└── runtime/      # agent shims (read-only)
```

The host is not visible. Never mounted: `/`, home dirs, `/etc`, `/var`,
`/proc`, `/sys`, `/dev`, any `*.sock` / named-pipe runtime socket.

## Workspace mounts (explicit only)

1. Caller passes a server-side path; it must resolve under the tenant
   workspace root (`OPENAGENT_WORKSPACE_ROOT`).
2. `..` escapes, bare symlinks, and non-existent paths rejected;
   ownership assumed validated by the workspace owner (Code Agent
   org-checks before handing the path over).
3. Mount recorded on the sandbox row; read-only unless profile allows RW.
4. Cleanup on destroy/expire via GC sweep.

## Symlink / hardlink / traversal defense

- String containment for not-yet-existing paths; realpath containment
  for existing ones (`validate_sandbox_path`).
- Artifact export re-checks `..` and mount-root containment; `docker cp`
  targets validated before copy.
- `ln -s /host/secret ./secret` inside the container resolves against
  the container root — the host is simply not there.

## Artifacts & uploads

- In: authenticate → authorize → validate → size/MIME check → isolated
  temp → optional scan → transfer → metadata.
- Out: validate → size cap (`max_artifacts_mb`) → secret scan → storage
  abstraction → tenant-scoped ref. Container paths never leave the server.
