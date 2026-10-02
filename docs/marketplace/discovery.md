# Discovery

Discovery runs over PUBLISHED listings in marketplaces visible to the
caller (public + own-org private). Private marketplace rows can never leak:
the visibility predicate is in SQL, and cross-tenant reads return 404.

## Query model

`MarketplaceSearchQuery`: text, marketplace, category, tags, package types,
publishers, pricing, license, trust, max risk, min rating, badges, sort,
page, page_size. The normalized filter spec is provider-neutral — the
built-in SQL builder executes it today; pgvector/OpenSearch/Elasticsearch
providers can execute the same spec later.

## Sorting (factual only)

RELEVANCE (transparent title/description/tag scoring), NEWEST, UPDATED,
MOST_INSTALLED (`install_count`), MOST_USED (`successful_install_count`),
MOST_FAVORITED, HIGHEST_RATED, PRICE_* (cheapest active price, free = 0).
Metric definitions live in `openagent/marketplace/types.py::METRIC_DEFINITIONS`
and are the only "popularity" signals — no raw page-view ranking.

## Recommendations

Rule-based with labeled reasons (same publisher, shared tags, same
category/type, org-installed siblings). No personal attribute inference,
no hidden scores; the UI renders the reasons next to each suggestion.

## SEO

Public listing pages use stable slugs, server-renderable metadata and a
sitemap architecture (`/marketplace/sitemap.xml` route pattern reserved;
canonical URLs are the listing slugs). No fake reviews or content are ever
generated for SEO.
