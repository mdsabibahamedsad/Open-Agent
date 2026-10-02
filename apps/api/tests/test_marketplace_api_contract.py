"""MP23 API contract tests: route registration (no database required)."""

from openagent.api.v1.marketplace import (
    advisories_router,
    commerce_router,
    distribution_router,
    favorites_router,
    listings_router,
    marketplace_router,
    marketplaces_router,
    moderation_router,
    notifications_router,
    publisher_router,
    publishers_router,
    reports_router,
    reviews_router,
)


def _routes(router):
    out = {}
    for r in router.routes:
        methods = tuple(sorted(getattr(r, "methods", set()) or set()))
        out.setdefault(getattr(r, "path", ""), set()).update(methods)
    return out


MARKETPLACES_REQUIRED = {
    "/organizations/{organization_id}/marketplaces": {"GET", "POST"},
    "/organizations/{organization_id}/marketplaces/{marketplace_id}": {"GET", "PATCH"},
    "/organizations/{organization_id}/marketplaces/{marketplace_id}/policy": {"GET", "PUT"},
}

DISCOVERY_REQUIRED = {
    "/marketplace/search": {"GET"},
    "/marketplace/categories": {"GET"},
    "/marketplace/featured": {"GET"},
    "/marketplace/registries": {"GET"},
    "/marketplace/{slug}": {"GET"},
    "/marketplace/{slug}/related": {"GET"},
}
LISTINGS_REQUIRED = {
    "/organizations/{organization_id}/listings": {"GET", "POST"},
    "/organizations/{organization_id}/listings/{listing_id}": {"GET", "PATCH"},
    "/organizations/{organization_id}/listings/{listing_id}/versions": {"GET", "POST"},
    "/organizations/{organization_id}/listings/{listing_id}/submit": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/approve": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/reject": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/request-changes": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/publish": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/suspend": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/restore": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/deprecate": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/revoke": {"POST"},
    "/organizations/{organization_id}/listings/{listing_id}/security": {"GET"},
    "/organizations/{organization_id}/listings/{listing_id}/health": {"GET"},
    "/organizations/{organization_id}/listings/{listing_id}/timeline": {"GET"},
    "/organizations/{organization_id}/listings/{listing_id}/analytics": {"GET"},
    "/organizations/{organization_id}/listings/{listing_id}/install": {"POST"},
}

PUBLISHERS_REQUIRED = {
    "/publishers": {"GET", "POST"},
    "/publishers/{slug}": {"GET", "PATCH"},
    "/publishers/{slug}/members": {"POST"},
    "/publishers/{slug}/members/{user_id}": {"DELETE"},
    "/publishers/{slug}/verification/request": {"POST"},
    "/publishers/{slug}/verification/decide": {"POST"},
    "/publishers/{slug}/follow": {"POST", "DELETE"},
    "/publishers/{slug}/analytics": {"GET"},
    "/publishers/{slug}/reviews": {"GET"},
}

REVIEWS_REQUIRED = {
    "/reviews": {"GET", "POST"},
    "/reviews/{review_id}": {"PATCH", "DELETE"},
    "/reviews/{review_id}/respond": {"POST"},
    "/reviews/{review_id}/report": {"POST"},
    "/reviews/{review_id}/moderate": {"POST"},
}

FAVORITES_REQUIRED = {
    "/favorites": {"GET", "POST"},
    "/favorites/{listing_id}": {"DELETE"},
}

ADVISORIES_REQUIRED = {
    "/security-advisories": {"GET", "POST"},
    "/security-advisories/{advisory_id}": {"GET", "PATCH"},
    "/security-advisories/{advisory_id}/affected": {"GET"},
}

REPORTS_REQUIRED = {
    "/marketplace-reports": {"GET", "POST"},
    "/marketplace-reports/{report_id}/triage": {"POST"},
}

MODERATION_REQUIRED = {
    "/master/marketplace/overview": {"GET"},
    "/master/marketplace/queue": {"GET"},
    "/master/marketplace/action": {"POST"},
    "/master/marketplace/events": {"GET"},
    "/master/marketplace/categories": {"POST"},
    "/master/marketplace/registries": {"POST"},
}

DISTRIBUTION_REQUIRED = {
    "/organizations/{organization_id}/distribution/artifacts": {"GET", "POST"},
    "/organizations/{organization_id}/distribution/artifacts/{artifact_id}/download": {"GET"},
    "/organizations/{organization_id}/distribution/artifacts/{artifact_id}/locations": {"POST"},
}

COMMERCE_REQUIRED = {
    "/organizations/{organization_id}/commerce/products": {"GET", "POST"},
    "/organizations/{organization_id}/commerce/products/{product_id}/prices": {"POST"},
    "/organizations/{organization_id}/commerce/products/{product_id}/activate": {"POST"},
    "/organizations/{organization_id}/commerce/entitlements": {"GET", "POST"},
    "/organizations/{organization_id}/commerce/webhooks/{provider}": {"POST"},
    "/organizations/{organization_id}/commerce/revenue": {"GET"},
    "/organizations/{organization_id}/commerce/payouts": {"GET"},
}

STUDIO_REQUIRED = {
    "/organizations/{organization_id}/publisher/profile": {"GET"},
    "/organizations/{organization_id}/publisher/listings": {"GET"},
    "/organizations/{organization_id}/publisher/packages": {"GET"},
    "/organizations/{organization_id}/publisher/analytics": {"GET"},
    "/organizations/{organization_id}/publisher/reviews": {"GET"},
    "/organizations/{organization_id}/publisher/security": {"GET"},
}

NOTIFICATIONS_REQUIRED = {
    "/organizations/{organization_id}/notifications": {"GET"},
    "/organizations/{organization_id}/notifications/{notification_id}/read": {"POST"},
    "/organizations/{organization_id}/notifications/prefs": {"GET", "PUT"},
}


class TestMarketplaceApiContract:
    def test_marketplaces_routes(self):
        routes = _routes(marketplaces_router)
        for path, methods in MARKETPLACES_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_discovery_routes(self):
        routes = _routes(marketplace_router)
        for path, methods in DISCOVERY_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_listings_routes(self):
        routes = _routes(listings_router)
        for path, methods in LISTINGS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_publishers_routes(self):
        routes = _routes(publishers_router)
        for path, methods in PUBLISHERS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_reviews_routes(self):
        routes = _routes(reviews_router)
        for path, methods in REVIEWS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_favorites_routes(self):
        routes = _routes(favorites_router)
        for path, methods in FAVORITES_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_advisories_routes(self):
        routes = _routes(advisories_router)
        for path, methods in ADVISORIES_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_reports_routes(self):
        routes = _routes(reports_router)
        for path, methods in REPORTS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_moderation_routes(self):
        routes = _routes(moderation_router)
        for path, methods in MODERATION_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_distribution_routes(self):
        routes = _routes(distribution_router)
        for path, methods in DISTRIBUTION_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_commerce_routes(self):
        routes = _routes(commerce_router)
        for path, methods in COMMERCE_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_studio_routes(self):
        routes = _routes(publisher_router)
        for path, methods in STUDIO_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"

    def test_notifications_routes(self):
        routes = _routes(notifications_router)
        for path, methods in NOTIFICATIONS_REQUIRED.items():
            assert path in routes, f"missing {path}"
            assert methods <= routes[path], f"{path}: missing {methods - routes[path]}"
