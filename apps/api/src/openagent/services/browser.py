"""Back-compat shim: openagent.services.browser re-exports the canonical BrowserService."""

from openagent.browser.service import (
    BrowserNotFound,
    BrowserPolicyDenied,
    BrowserSecurityError,
    BrowserService,
)

__all__ = ["BrowserService", "BrowserSecurityError", "BrowserPolicyDenied", "BrowserNotFound"]
