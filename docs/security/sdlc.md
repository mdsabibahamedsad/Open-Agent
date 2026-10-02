# Secure Development Lifecycle

Design → threat model (`threat-model.md`) → implementation →
security tests (auth/authZ/SSO/SCIM/zero-trust/AI/tenant/failure
matrix) → review → release. CI (`security-gate` job + the additions
below) runs dependency scanning, secret scanning, static analysis,
and container/IaC hooks with blocking/warning/informational tiers.
Production dependencies are never auto-upgraded without compat
testing. Supply chain: lockfiles, checksums, provenance metadata,
image-signing hooks, SBOM (`scripts/sbom.py`, SPDX/CycloneDX) —
signed provenance is claimed only when generated and verified.
