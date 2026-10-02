# Marketplace Architecture (MP22 foundation, MP23 commerce)

## Separation

```
OpenAgent Core
  → Package System (this phase: definitions, versions, validation, install)
    → Registry (content-addressed bundles, signatures, publisher identity)
      → Marketplace (discovery, reviews, analytics — MP23)
        → Commerce (payments, subscriptions, revenue sharing — MP23)
```

Core runs fully without registry/marketplace/commerce. Local deployments
create, import, export, install and run everything offline.

## Catalog (this phase)

- SQL-backed search: full-text match, category/tag/type/author/trust/
  security/installed filters, transparent ranking (match → trust → recency).
- `CatalogProvider` protocol allows future pgvector / Elasticsearch /
  OpenSearch / hosted semantic search without API or UI changes.
- Marketplace-ready metadata on every package (icon, screenshots hooks,
  author/publisher, license, categories, features, requirements,
  compatibility, trust); stubs reserved for ratings, downloads, installs,
  forks, favorites, verified publishers and analytics — no fake numbers.

## Deferred to MP23 (with ready interfaces)

Free/paid templates, subscriptions, enterprise/private marketplaces,
verified publisher accounts, creator revenue sharing, usage-based packages,
reviews/ratings, download analytics, CDN distribution. Payment logic is
never coupled to the core runtime.

## Categories

AI & Agents, Automation, Business, Marketing, Sales, Customer Support,
Developer Tools, Coding, Research, Data, Productivity, Finance, Operations,
Content, SEO, Social Media, Browser Automation, DevOps, Security, Education,
Personal Assistant, Enterprise — plus admin-managed custom categories
(`package_categories`; official seeds in migration 021).
