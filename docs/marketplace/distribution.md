# Distribution

`ArtifactStorage` (protocol) abstracts upload/download/delete/exists over
the existing `core.storage` backends. `LocalArtifactStorage` (self-hosting
default) stores bytes under content-addressed keys
`<prefix>/<aa>/<bb>/<sha256>-<name>` — identical bytes stored once,
corruption detectable on every read.

## Artifact lifecycle

`PENDING -> VERIFYING -> VERIFIED|REJECTED`, with `PUBLISHED` once a
verified artifact backs a published listing version. Verification checks:
size limits (100MB archive / 500MB extracted / 2000 files), MIME by type,
safe member names (no traversal, no absolute paths), single-file and
compression-ratio bomb guards, manifest presence for package archives,
sha256 match, and MP22 signature state. Failures reject with reasons;
nothing unverified is downloadable or installable.

## Locations and mirrors

`distribution_locations` records where an artifact lives (LOCAL primary,
plus CDN/registry/GitHub refs). Mirroring is configuration
(`mirror_of` chains on registries), not a sync engine — full CDN
synchronization is MP24. Upload failures retry; verification failures
reject; storage failures fall back to alternate locations; publish waits
for integrity success.

## Limits (server-side, enforced)

Package archives 100MB, extracted 500MB, single member 50MB, assets 25MB
(images/video/docs only; executables and active types blocked), listing
links 20, review bodies 20KB. Limits live in
`openagent/marketplace/distribution.py` and the API layer.
