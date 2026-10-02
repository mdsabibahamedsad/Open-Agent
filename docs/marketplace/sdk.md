# Marketplace SDK & CLI

All examples below call real APIs — only documented endpoints are shown.
OpenAPI (`/docs`) exposes every marketplace tag: `marketplaces`,
`marketplace`, `listings`, `publishers`, `reviews`, `favorites`,
`security-advisories`, `marketplace-reports`, `marketplace-moderation`,
`distribution`, `commerce`, `publisher-studio`, `notifications`.

## TypeScript SDK (`packages/sdk`)

```ts
import { createSDK } from '@openagent/sdk';

const sdk = createSDK({ apiUrl, apiKey, organizationId });

// Discovery
const hits = await sdk.marketplace.search({ q: 'research', sort: 'HIGHEST_RATED' });
const detail = await sdk.marketplace.get('research-workforce');
const related = await sdk.marketplace.related('research-workforce');

// Install (entitlement-gated server-side; 402 when purchase is required)
const job = await sdk.marketplace.install(listingId, { version: '1.2.0', values: {} });

// Publishers & listings
const pub = await sdk.publishers.create({ display_name: 'Acme', slug: 'acme' });
const listing = await sdk.listings.create({
  marketplace_id, package_id, publisher_id, slug: 'acme-research',
  title: 'Acme Research', pricing_model: 'FREE',
});
await sdk.listings.submit(listing.id);
await sdk.listings.publish(listing.id); // approved listings, publisher owner/admin
await sdk.listings.health(listing.id);

// Reviews (pinned to the installed version)
await sdk.reviews.create({ listing_id, installation_id, rating: 5, title: 'Solid', body: '...' });
await sdk.reviews.report(reviewId, { reason: 'SPAM' });

// Advisories & distribution
const advisories = await sdk.advisories.list({ status: 'AFFECTED' });
const artifacts = await sdk.distribution.artifacts(versionId);
```

## CLI (`scripts/openagent_package.py`)

```bash
export OPENAGENT_API_URL=http://localhost:8000
export OPENAGENT_API_KEY=<key> OPENAGENT_ORG_ID=<org>

openagent-package marketplace search "research" --sort HIGHEST_RATED
openagent-package marketplace inspect research-workforce
openagent-package marketplace install <listing-id> --version 1.2.0

openagent-package publisher init --slug acme --name Acme
openagent-package publisher validate acme
openagent-package publisher submit <listing-id>
openagent-package publisher status <listing-id>
```

Every command performs real API calls; offline commands (`validate`,
`build`, `export`, `import`, `inspect`, `template validate`) need no
server. `marketplace install` surfaces entitlement outcomes honestly
(`NEED_ENTITLEMENT` / `COMMERCE_DISABLED` with HTTP 402).
