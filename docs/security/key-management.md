# Key Management

`KeyManagementProvider` abstraction (encrypt/decrypt/rotate) over the
existing credential crypto, ready for KMS/HSM/Vault/cloud managers.
Covers encryption keys, signing keys (with key IDs + published
verification keys, unknown/expired rejected), SSO certificates, API
credentials, service identities. Encryption at rest via configured
providers, TLS in transit, no custom cryptography, customer-managed
keys prepared as an interface. All rotations auditable.
