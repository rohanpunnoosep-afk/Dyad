# Frontend integration

`frontend/` is the canonical TANDEM Vite/React application in this repository. Its happy-path UI simulates buyer, seller, and middleman messages using the shapes defined in [`../json_formats.md`](../json_formats.md). No service or model API is connected by the frontend. The two workspaces share a local browser session, not a hosted database.

## Deployment configurations

| File | Intended use |
| --- | --- |
| `frontend/vercel.json` | Current frontend deployment: set Vercel Root Directory to `frontend`, run `npm run build`, serve `dist/`. No Python function declaration. |
| `frontend/deployment/vercel.integrated.json` | Template for the combined repository when `api/index.py` and its backend dependencies are present. |

For a future combined deployment, merge the template into the repository's root `vercel.json`. It installs and builds the app from `frontend/` and serves `frontend/dist/`. Vercel will not automatically read the nested template. Keep any additional backend settings required by that repository. The current frontend addition does not change that existing root configuration.

The template retains the existing `/api/(.*)` → `/api/index` rewrite and `api/index.py` maximum duration of 300 seconds. It adds the Vite build/output settings and a frontend fallback that excludes `/api`, `/assets/`, `/images/`, and the favicon. API requests must reach the backend rather than return frontend HTML. Do not use this template as the standalone checkout's root configuration while the Python function is absent.

The combined-deployment template is inactive. Its presence does not establish a working API connection or a deployed backend.

## Connection points

- `src/data/inventory.json` is the canonical seeded seller catalog, with one record per size-specific SKU. Its fields match the inventory schema exactly: `sku`, `name`, `category`, `color`, `material`, `size`, `price`, `stock`, and `image`.
- `src/data/product-meta.json` holds presentation metadata separately, including style and fit tags. This metadata is not part of the inventory message schema.
- `src/contracts.ts` represents the repository's JSON message contract in TypeScript.
- `src/catalog.ts` resolves inventory image filenames for frontend display, adapts catalog data, and provides the local demo generation and scoring helpers.
- `src/store.ts` owns the shared session, serialized exchange state, `localStorage`, and `BroadcastChannel` synchronization.
- `src/main.tsx` owns onboarding, progress, the five-bundle report, ratings and analysis presentation, and the final-offer decision UI.

The `image` field remains a filename in inventory and messages. Bundle `images` follow the order of their `skus`. Resolve filenames to frontend assets at the display boundary rather than replacing the wire fields with URLs. Each size is an individual SKU; do not reconstruct a product with a sizes array in the API payload.

## Exchange and constraints

The single-round flow is:

1. Serialize the buyer's selected looks and chat into context: `style`, preferred and avoided colors, `sizes`, `budget`, `occasion`, and `notes`.
2. The seller provides exactly five distinct bundles with SKU references, image filenames, item totals, and bundle prices.
3. The middleman checks the bundles against the contract and buyer constraints.
4. The buyer returns one rating per bundle: `id`, `probability` between 0 and 1, and an item-specific `reason`.
5. The seller analyzes the ratings and identifies useful and unsuitable attributes and SKUs.
6. The seller returns exactly one final offer, including `savings` and `why`; the middleman checks it again.
7. The buyer returns an `accept` or `reject` decision for that final offer.

The frontend's mock ratings describe purchase chance at the offered price. They are independent estimates rather than a distribution over five choices. Price, fit, and style scores are auxiliary display values, not replacements for contract `probability`. No calibrated model is producing these estimates in the demo.

Sizes, budget, avoided colors, and explicit notes are hard rules. Offer variation comes from valid combinations and softer style, fabric, coverage, and price tradeoffs; it must not introduce wrong-size or over-budget offers. Only in-stock SKUs may appear. Item totals and savings are computed from catalog prices. Seller item and discount limits also apply.

Replace the local simulation and progress timing with validated service responses at each stage. Keep the five-bundle ratings → seller analysis → one final offer sequence; accepting an initial bundle is not the final contract decision. Preserve the same agreed SKUs, sizes, and total in both workspaces.

The current store only synchronizes tabs/windows sharing the same browser profile and origin. A backend integration will need a shared session identifier and server updates for separate devices or browser profiles. Preset role buttons provide no authenticated identity. The local JSON catalog and browser session do not provide server persistence, stock reservation, payment, or fulfillment.

