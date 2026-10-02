"""Browser domain package (provider-neutral orchestration, policy-aware)."""

from openagent.browser.security import (
    classify_risk,
    detect_challenge,
    detect_loop,
    detect_prompt_injection,
    evaluate_domain_policy,
    fingerprint_state,
    is_retry_safe,
    label_untrusted,
    redact_dict,
    redact_text,
    requires_approval,
    sanitize_url,
    validate_redirect,
    validate_url,
)
from openagent.browser.service import BrowserNotFound, BrowserPolicyDenied, BrowserSecurityError, BrowserService
from openagent.browser.tools import BROWSER_TOOLS, BrowserToolExecutor, ensure_browser_tools_registered
from openagent.browser.observations import compress_observation
from openagent.browser.client import BrowserClient

__all__ = [
    "BrowserService", "BrowserSecurityError", "BrowserPolicyDenied", "BrowserNotFound",
    "BROWSER_TOOLS", "BrowserToolExecutor", "ensure_browser_tools_registered", "compress_observation",
    "BrowserClient",
    "validate_url", "validate_redirect", "evaluate_domain_policy", "sanitize_url",
    "redact_text", "redact_dict", "detect_prompt_injection", "label_untrusted",
    "detect_challenge", "classify_risk", "requires_approval", "is_retry_safe",
    "fingerprint_state", "detect_loop",
]
