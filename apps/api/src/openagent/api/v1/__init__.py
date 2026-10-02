"""Versioned API router: assembles all v1 sub-routers (single canonical entry)."""

from fastapi import APIRouter

from openagent.api.health import router as health_router
from openagent.api.v1.auth import router as auth_router
from openagent.api.v1.rbac import router as rbac_router
from openagent.api.v1.teams import router as teams_router
from openagent.api.v1.invitations import router as invitations_router
from openagent.api.v1.service_accounts import router as service_accounts_router
from openagent.api.v1.workflows import router as workflows_router
from openagent.api.v1.workflow_executions import router as workflow_executions_router
from openagent.api.v1.agents import router as agents_router
from openagent.api.v1.tools import router as tools_router
from openagent.api.v1.mcp import router as mcp_router
from openagent.api.v1.orchestrations import router as orchestrations_router
from openagent.api.v1.memory import router as memory_router
from openagent.api.v1.management import router as management_router
from openagent.api.v1.browser import router as browser_router
from openagent.api.v1.repositories import router as repositories_router
from openagent.api.v1.code import router as code_router
from openagent.api.v1.sandboxes import router as sandboxes_router
from openagent.api.v1.sandboxes import profiles_router as sandbox_profiles_router
from openagent.api.v1.sandboxes import exec_router as sandbox_executions_router
from openagent.api.v1.approvals import (router as approvals_router,
                                        policies_router as approval_policies_router,
                                        delegations_router as approval_delegations_router)
from openagent.api.v1.evaluations import (router as evaluations_router,
                                          rubrics_router as evaluation_rubrics_router,
                                          gates_router as quality_gates_router,
                                          benchmarks_router as benchmarks_router,
                                          attempts_router as correction_plans_router,
                                          quality_router as quality_router)
from openagent.api.v1.integrations import (router as connectors_router,
                                           connections_router as integration_connections_router,
                                           credentials_router as connector_credentials_router,
                                           webhooks_mgmt_router as connector_webhooks_router,
                                           webhooks_router as inbound_webhooks_router)
from openagent.api.v1.packages import (router as packages_router,
                                       skills_router as package_skills_router,
                                       presets_router as package_presets_router,
                                       catalog_router as package_catalog_router,
                                       installations_router as package_installations_router)
from openagent.api.v1.marketplace import (
    advisories_router as marketplace_advisories_router,
    commerce_router as marketplace_commerce_router,
    distribution_router as marketplace_distribution_router,
    favorites_router as marketplace_favorites_router,
    listings_router as marketplace_listings_router,
    marketplace_router as marketplace_discovery_router,
    marketplaces_router as marketplaces_router,
    moderation_router as marketplace_moderation_router,
    notifications_router as marketplace_notifications_router,
    publisher_router as publisher_studio_router,
    publishers_router as publishers_router,
    reports_router as marketplace_reports_router,
    reviews_router as reviews_router,
)
from openagent.api.v1.commerce import (
    billing_router as commerce_billing_router,
    checkout_router as commerce_checkout_router,
    prices_router as commerce_prices_router,
    products_router as commerce_products_router,
    registries_router as commerce_registries_router,
)
from openagent.api.v1.commerce_ops import (
    credits_router as commerce_credits_router,
    entitlements_router as commerce_entitlements_router,
    quotas_router as commerce_quotas_router,
    subscriptions_router as commerce_subscriptions_router,
    usage_router as commerce_usage_router,
)
from openagent.api.v1.commerce_billing import (
    disputes_router as commerce_disputes_router,
    invoices_router as commerce_invoices_router,
    master_billing_router as commerce_master_router,
    payouts_router as commerce_payouts_router,
    promotions_router as commerce_promotions_router,
    refunds_router as commerce_refunds_router,
    revenue_router as commerce_revenue_router,
    webhooks_router as commerce_webhooks_router,
)
from openagent.api.v1.cloud import (
    router as cloud_router,
    regions_router as cloud_regions_router,
    master_router as cloud_master_router,
)
from openagent.api.v1.cloud_files import router as cloud_files_router
from openagent.api.v1.cloud_workers import router as cloud_workers_router
from openagent.api.v1.operations import router as operations_router
from openagent.api.v1.platform import router as platform_control_router
from openagent.api.v1.enterprise import router as enterprise_router
from openagent.api.v1.identity import router as identity_router
from openagent.api.v1.scim import router as scim_router
from openagent.api.v1.developer import (
    extensions_router as developer_extensions_router,
    local_registry_router as developer_local_registry_router,
    public_router as developer_public_router,
    router as developer_router,
)

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(rbac_router)
router.include_router(teams_router)
router.include_router(invitations_router)
router.include_router(service_accounts_router)
router.include_router(workflows_router)
router.include_router(workflow_executions_router)
router.include_router(agents_router)
router.include_router(tools_router)
router.include_router(mcp_router)
router.include_router(orchestrations_router)
router.include_router(memory_router)
router.include_router(management_router)
router.include_router(browser_router)
router.include_router(repositories_router)
router.include_router(code_router)
router.include_router(sandboxes_router)
router.include_router(sandbox_profiles_router)
router.include_router(sandbox_executions_router)
router.include_router(approvals_router)
router.include_router(approval_policies_router)
router.include_router(approval_delegations_router)
router.include_router(evaluations_router)
router.include_router(evaluation_rubrics_router)
router.include_router(quality_gates_router)
router.include_router(benchmarks_router)
router.include_router(correction_plans_router)
router.include_router(quality_router)
router.include_router(connectors_router)
router.include_router(integration_connections_router)
router.include_router(connector_credentials_router)
router.include_router(connector_webhooks_router)
router.include_router(inbound_webhooks_router)
router.include_router(packages_router)
router.include_router(package_skills_router)
router.include_router(package_presets_router)
router.include_router(package_catalog_router)
router.include_router(package_installations_router)
router.include_router(marketplaces_router)
router.include_router(marketplace_discovery_router)
router.include_router(marketplace_listings_router)
router.include_router(publishers_router)
router.include_router(reviews_router)
router.include_router(marketplace_favorites_router)
router.include_router(marketplace_advisories_router)
router.include_router(marketplace_reports_router)
router.include_router(marketplace_moderation_router)
router.include_router(marketplace_distribution_router)
router.include_router(marketplace_commerce_router)
router.include_router(publisher_studio_router)
router.include_router(marketplace_notifications_router)
router.include_router(commerce_registries_router)
router.include_router(commerce_products_router)
router.include_router(commerce_prices_router)
router.include_router(commerce_checkout_router)
router.include_router(commerce_subscriptions_router)
router.include_router(commerce_entitlements_router)
router.include_router(commerce_usage_router)
router.include_router(commerce_quotas_router)
router.include_router(commerce_invoices_router)
router.include_router(commerce_refunds_router)
router.include_router(commerce_disputes_router)
router.include_router(commerce_credits_router)
router.include_router(commerce_revenue_router)
router.include_router(commerce_payouts_router)
router.include_router(commerce_promotions_router)
router.include_router(commerce_billing_router)
router.include_router(commerce_webhooks_router)
router.include_router(commerce_master_router)
router.include_router(cloud_router)
router.include_router(cloud_regions_router)
router.include_router(cloud_files_router)
router.include_router(cloud_workers_router)
router.include_router(cloud_master_router)
router.include_router(operations_router)
router.include_router(platform_control_router)
router.include_router(enterprise_router)
router.include_router(identity_router)
router.include_router(scim_router)
router.include_router(developer_router)
router.include_router(developer_extensions_router)
router.include_router(developer_public_router)
router.include_router(developer_local_registry_router)

__all__ = [
    "router",
    "memory_router",
    "orchestrations_router",
    "management_router",
    "agents_router",
    "workflows_router",
    "workflow_executions_router",
    "tools_router",
    "mcp_router",
    "auth_router",
    "rbac_router",
    "teams_router",
    "invitations_router",
    "service_accounts_router",
    "health_router",
    "browser_router",
    "repositories_router",
    "code_router",
    "sandboxes_router",
    "sandbox_profiles_router",
    "sandbox_executions_router",
    "approvals_router",
    "approval_policies_router",
    "approval_delegations_router",
    "evaluations_router",
    "evaluation_rubrics_router",
    "quality_gates_router",
    "benchmarks_router",
    "correction_plans_router",
    "quality_router",
    "connectors_router",
    "integration_connections_router",
    "connector_credentials_router",
    "connector_webhooks_router",
    "inbound_webhooks_router",
    "packages_router",
    "package_skills_router",
    "package_presets_router",
    "package_catalog_router",
    "package_installations_router",
    "marketplaces_router",
    "marketplace_discovery_router",
    "marketplace_listings_router",
    "publishers_router",
    "reviews_router",
    "marketplace_favorites_router",
    "marketplace_advisories_router",
    "marketplace_reports_router",
    "marketplace_moderation_router",
    "marketplace_distribution_router",
    "marketplace_commerce_router",
    "publisher_studio_router",
    "marketplace_notifications_router",
    "commerce_registries_router",
    "commerce_products_router",
    "commerce_prices_router",
    "commerce_checkout_router",
    "commerce_subscriptions_router",
    "commerce_entitlements_router",
    "commerce_usage_router",
    "commerce_quotas_router",
    "commerce_invoices_router",
    "commerce_refunds_router",
    "commerce_disputes_router",
    "commerce_credits_router",
    "commerce_revenue_router",
    "commerce_payouts_router",
    "commerce_promotions_router",
    "commerce_billing_router",
    "commerce_webhooks_router",
    "commerce_master_router",
    "cloud_router",
    "cloud_regions_router",
    "cloud_files_router",
    "cloud_workers_router",
    "cloud_master_router",
    "operations_router",
    "platform_control_router",
    "enterprise_router",
    "identity_router",
    "scim_router",
]
