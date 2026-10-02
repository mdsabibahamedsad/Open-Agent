"""MP22 API contract tests: route registration (no database required)."""

from openagent.api.v1.packages import (
    catalog_router,
    installations_router,
    presets_router,
    router as packages_router,
    skills_router,
)


def _routes(router):
    out = {}
    for r in router.routes:
        methods = tuple(sorted(getattr(r, "methods", set()) or set()))
        out.setdefault(getattr(r, "path", ""), set()).update(methods)
    return out


PACKAGES_REQUIRED = {
    "/organizations/{organization_id}/packages": {"GET", "POST"},
    "/organizations/{organization_id}/packages/import": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}": {"GET", "PATCH", "DELETE"},
    "/organizations/{organization_id}/packages/{package_id}/versions": {"GET", "POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}": {"GET"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/validate": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/publish": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/deprecate": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/revoke": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{v1}/diff/{v2}": {"GET"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/security": {"GET"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/install-preview": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/install": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/versions/{version}/export": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/fork": {"POST"},
    "/organizations/{organization_id}/packages/{package_id}/assets/validate": {"POST"},
}

SKILLS_REQUIRED = {
    "/organizations/{organization_id}/skills": {"GET", "POST"},
    "/organizations/{organization_id}/skills/{skill_id}": {"GET"},
    "/organizations/{organization_id}/skills/{skill_id}/versions": {"POST"},
    "/organizations/{organization_id}/skills/{skill_id}/versions/{version}/publish": {"POST"},
    "/organizations/{organization_id}/skills/{skill_id}/validate": {"POST"},
    "/organizations/{organization_id}/skills/{skill_id}/attach": {"POST"},
}

PRESETS_REQUIRED = {
    "/organizations/{organization_id}/presets": {"GET", "POST"},
    "/organizations/{organization_id}/presets/{preset_id}": {"GET"},
    "/organizations/{organization_id}/presets/{preset_id}/versions": {"POST"},
    "/organizations/{organization_id}/presets/{preset_id}/versions/{version}/publish": {"POST"},
}

CATALOG_REQUIRED = {
    "/organizations/{organization_id}/catalog/search": {"GET"},
    "/organizations/{organization_id}/catalog/categories": {"GET"},
}

INSTALLATIONS_REQUIRED = {
    "/organizations/{organization_id}/installations": {"GET"},
    "/organizations/{organization_id}/installations/{installation_id}": {"GET", "DELETE"},
    "/organizations/{organization_id}/installations/{installation_id}/update-plan": {"POST"},
    "/organizations/{organization_id}/installations/{installation_id}/update": {"POST"},
    "/organizations/{organization_id}/installations/{installation_id}/rollback": {"POST"},
}


class TestPackagesApiContract:
    def test_packages_routes(self):
        routes = _routes(packages_router)
        for path, methods in PACKAGES_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_skills_routes(self):
        routes = _routes(skills_router)
        for path, methods in SKILLS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_presets_routes(self):
        routes = _routes(presets_router)
        for path, methods in PRESETS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_catalog_routes(self):
        routes = _routes(catalog_router)
        for path, methods in CATALOG_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_installations_routes(self):
        routes = _routes(installations_router)
        for path, methods in INSTALLATIONS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"
