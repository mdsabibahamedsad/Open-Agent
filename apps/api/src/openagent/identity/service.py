"""MP27: identity service facade — assembles lifecycle, IdPs,
policies, simulator, workload broker, DLP, and notifications."""

from __future__ import annotations

from typing import Any, Optional

from openagent.identity.abac import Authorizer
from openagent.identity.dlp import DataPolicyEngine
from openagent.identity.lifecycle import IdentityRegistry
from openagent.identity.providers import IdentityProvider, LocalIdentityProvider
from openagent.identity.secpolicies import PolicySimulator, PolicyStore
from openagent.identity.trust import RevocationRegistry
from openagent.identity.workload import CredentialBroker


class IdentityService:
    def __init__(self) -> None:
        self.identities = IdentityRegistry()
        self.authorizer = Authorizer()
        self.policies = PolicyStore()
        self.broker = CredentialBroker()
        self.dlp = DataPolicyEngine()
        self.revocations = RevocationRegistry()
        self._providers: dict[str, IdentityProvider] = {
            "local": LocalIdentityProvider(),
        }

    def register_provider(self, provider_id: str,
                          provider: IdentityProvider) -> None:
        self._providers[provider_id] = provider

    def provider(self, provider_id: str) -> IdentityProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ValueError(f"unknown identity provider {provider_id}")

    def simulator(self) -> PolicySimulator:
        return PolicySimulator(self.policies)


_service: Optional[IdentityService] = None


def get_identity_service() -> IdentityService:
    global _service
    if _service is None:
        _service = IdentityService()
    return _service


def reset_identity_service() -> None:
    global _service
    _service = None
