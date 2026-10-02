# Object storage

Provider-neutral `ObjectStorageProvider` (`put/get/delete/exists/list/
presigned_url/copy/move/metadata`). Baselines: filesystem (dev),
in-memory fake (tests), S3-compatible (MinIO/AWS/R2/GCS-interop, lazy
`boto3`). Categories isolate boundaries (`execution-artifacts`,
`workflow-exports`, `agent-files`, `browser-downloads`, `code-patches`,
`build-artifacts`, `logs`, `datasets`, `documents`, `user-uploads`,
`marketplace-packages`). Artifacts validate checksum/size/MIME/
extension + malware-scan hook, quarantine on failure, and download via
signed org-bound expiring tokens (download limits, no raw credentials).
Large outputs live in storage; Postgres keeps metadata + refs.
