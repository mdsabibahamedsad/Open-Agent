"""MP21 connector framework public surface."""

from openagent.connectors.config import ConnectorSettings
from openagent.connectors.crypto import (
    CredentialCryptoError,
    decrypt_secret,
    encrypt_secret,
    generate_webhook_secret,
    mask_credential_payload,
    mask_secret,
)
from openagent.connectors.db_connector import (
    DatabaseError,
    classify_statement,
    validate_query,
)
from openagent.connectors.engine import ConnectorEngine, ConnectorError
from openagent.connectors.errors import (
    ProviderError,
    ProviderErrorKind,
    normalize_exception,
    normalize_http_error,
)
from openagent.connectors.http_client import ProviderHTTPClient, shared_client
from openagent.connectors.manifest import (
    ManifestError,
    manifest_hash,
    manifest_to_dict,
    validate_manifest,
)
from openagent.connectors.mapping import (
    apply_mapping,
    apply_transform,
    resolve_path,
)
from openagent.connectors.metrics import inc as metrics_inc
from openagent.connectors.metrics import snapshot as metrics_snapshot
from openagent.connectors.netsec import SSRFError, assert_host_safe, assert_url_safe
from openagent.connectors.oauth import (
    OAuthConfig,
    OAuthError,
    OAuthManager,
    TokenSet,
    build_authorize_url,
    pkce_pair,
    sign_state,
    validate_callback_url,
    verify_state,
)
from openagent.connectors.pagination import PageResult, PageSpec, Paginator
from openagent.connectors.polling import (
    PollCursor,
    PollResult,
    backoff_delay,
    run_poll_cycle,
)
from openagent.connectors.ratelimit import (
    RateLimitDecision,
    RateLimitState,
    check,
    parse_headers,
    record_call,
)
from openagent.connectors.registry import ConnectorRegistry, RegistryError, registry
from openagent.connectors.resources import normalize as normalize_resource
from openagent.connectors.retry import RetryDecision, decide_retry
from openagent.connectors.types import (
    TRUST_RANK,
    ActionDef,
    AuthType,
    CapabilityDef,
    ConnectorExecutionContext,
    ConnectorManifest,
    ConnectorScope,
    ConnectorStatus,
    ConnectorType,
    HealthState,
    InstanceStatus,
    ResourceDef,
    RiskLevel,
    SharingPolicy,
    TriggerDef,
    TriggerKind,
    TrustTier,
    can_transition_connector,
    can_transition_instance,
)
from openagent.connectors.webhooks import (
    NormalizedEvent,
    ReplayGuard,
    WebhookError,
    check_timestamp,
    normalize_event,
    verify_hmac,
    verify_signature,
)

__all__ = [
    "ConnectorType", "ConnectorStatus", "InstanceStatus", "ConnectorScope",
    "SharingPolicy", "AuthType", "TrustTier", "HealthState", "TriggerKind",
    "RiskLevel", "CapabilityDef", "ActionDef", "TriggerDef", "ResourceDef",
    "ConnectorManifest", "ConnectorExecutionContext", "TRUST_RANK",
    "can_transition_connector", "can_transition_instance",
    "ManifestError", "validate_manifest", "manifest_hash", "manifest_to_dict",
    "ConnectorRegistry", "RegistryError", "registry",
    "CredentialCryptoError", "encrypt_secret", "decrypt_secret",
    "mask_secret", "mask_credential_payload", "generate_webhook_secret",
    "SSRFError", "assert_host_safe", "assert_url_safe",
    "ProviderError", "ProviderErrorKind", "normalize_http_error",
    "normalize_exception", "decide_retry", "RetryDecision",
    "RateLimitState", "RateLimitDecision", "parse_headers", "check",
    "record_call", "PageSpec", "PageResult", "Paginator",
    "ProviderHTTPClient", "shared_client",
    "OAuthError", "OAuthConfig", "TokenSet", "OAuthManager",
    "pkce_pair", "sign_state", "verify_state", "build_authorize_url",
    "validate_callback_url", "WebhookError", "NormalizedEvent",
    "verify_signature", "verify_hmac", "check_timestamp", "ReplayGuard",
    "normalize_event", "PollCursor", "PollResult", "backoff_delay",
    "run_poll_cycle", "resolve_path", "apply_transform", "apply_mapping",
    "normalize_resource", "ConnectorEngine", "ConnectorError",
    "DatabaseError", "classify_statement", "validate_query",
    "metrics_inc", "metrics_snapshot", "ConnectorSettings",
]
