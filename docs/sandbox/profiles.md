# Sandbox — Execution Profiles

Reusable, validated bundles of limits + policy. Custom org overlays are
validated identically (`POST /api/v1/sandbox-profiles`).

| Profile | Level | CPU | Mem | Disk | PIDs | Timeout | Network | FS | Shell |
|---|---|---|---|---|---|---|---|---|---|
| `READ_ONLY` | 0 | 0.25 | 256MB | 512MB | 32 | 60s | none | RO | no |
| `TEST` | 1 | 1 | 1GB | 2GB | 128 | 600s | none | RW | no |
| `LINT` | 1 | 0.5 | 512MB | 1GB | 64 | 300s | none | RW | no |
| `TYPECHECK` | 1 | 0.5 | 1GB | 1GB | 64 | 300s | none | RW | no |
| `BUILD` | 1 | 2 | 2GB | 4GB | 256 | 1200s | none | RW | no |
| `PACKAGE` | 2 | 1 | 1GB | 4GB | 128 | 900s | allowlist* | RW | no |
| `DEVELOPMENT` | 3 | 2 | 2GB | 8GB | 256 | 3600s | restricted | RW | yes |
| `DATA_PROCESSING` | 1 | 2 | 4GB | 10GB | 128 | 3600s | none | RW | no |
| `CUSTOM` | 1 | 1 | 1GB | 2GB | 128 | 300s | none | RW | no |

\* `PACKAGE` allowlist covers PyPI, npm, crates.io, Go proxy, Maven,
Gradle, NuGet, GitHub.

## Security levels

- `LEVEL_0` read-only · `LEVEL_1` restricted execution ·
  `LEVEL_2` controlled network · `LEVEL_3` developer environment ·
  `LEVEL_4` elevated approved execution
- Gates: any network needs LEVEL_2+; `FULL_OUTBOUND`, untrusted images,
  or writable rootfs need LEVEL_4/LEVEL_3 respectively; shell needs
  LEVEL_3+. Higher capability without level = invalid profile (deny).

## Rules

- Profiles exceeding server caps (`SANDBOX_MAX_*`) are **denied**, not trimmed.
- `CUSTOM` overlays replace policy blocks wholesale and re-validate.
- Record the exact image (+digest) per execution; production requires digests.
- Code Agent mapping: `TEST→TEST`, `LINT→LINT`, `TYPECHECK→TYPECHECK`,
  `BUILD→BUILD`, `PACKAGE→PACKAGE`, `MIGRATION/CUSTOM→CUSTOM`,
  `DEV_SERVER→DEVELOPMENT`.
