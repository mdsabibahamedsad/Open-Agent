"""MP22: Reusable packages / templates / skills / presets foundation.

Public surface of the ``openagent.packages`` domain. The domain is split
into pure (DB-free) modules so validation, versioning, dependency
resolution, security scanning, signing and packaging can be unit-tested
without a database:

- :mod:`openagent.packages.types` — shared enums and constants
- :mod:`openagent.packages.versioning` — semver parsing + constraints
- :mod:`openagent.packages.manifest` — manifest parse / normalize / validate
- :mod:`openagent.packages.config_schema` — declarative configuration
- :mod:`openagent.packages.dependencies` — dependency resolver
- :mod:`openagent.packages.security` — security scanner + trust policy
- :mod:`openagent.packages.signing` — hashing + signing interfaces
- :mod:`openagent.packages.validation` — publication validation engine
- :mod:`openagent.packages.packaging` — export / import (portable format)
- :mod:`openagent.packages.installer` — preview / install / update / rollback
- :mod:`openagent.packages.catalog` — provider-neutral search abstraction
- :mod:`openagent.packages.graph` — resource graph + impact analysis
"""

from openagent.packages.types import (
    PACKAGE_FORMAT,
    PACKAGE_FORMAT_VERSION,
    STANDARD_CATEGORIES,
    SUPPORTED_LICENSES,
    InstallationStatus,
    PackageStatus,
    PackageType,
    PresetKind,
    ResourceType,
    Severity,
    TrustLevel,
    Visibility,
)

__all__ = [
    "PACKAGE_FORMAT",
    "PACKAGE_FORMAT_VERSION",
    "STANDARD_CATEGORIES",
    "SUPPORTED_LICENSES",
    "InstallationStatus",
    "PackageStatus",
    "PackageType",
    "PresetKind",
    "ResourceType",
    "Severity",
    "TrustLevel",
    "Visibility",
]
