# Tandem frontend

TANDEM is a happy-path menswear marketplace demo with separate buyer and seller workspaces. The buyer selects Casual and Athletic, saves three lounge-inspired looks, and answers a short context chat. The seller reviews prepopulated inventory and sets item and discount limits.

The simulated exchange follows the repository's [JSON contract](../json_formats.md): buyer context → five seller bundles → buyer ratings → seller analysis → one final offer → buyer decision. The five initial bundles provide different combinations, prices, fabrics, and style directions for the seller to learn from. They are not five checkout choices. The final offer aims for approximately $150 and must respect the buyer's budget and sizes.

## Run

From this folder, with Node.js 22.12 or newer:

```sh
npm ci
npm run dev
```

Open `?role=buyer` and `?role=seller` in two tabs or windows of the same browser, origin, and profile. **Reset demo** clears both workspaces. Default buyer preferences are Los Angeles, medium tops and bottoms, relaxed fit, and a $200 budget. Budget and sizes become hard constraints in the serialized buyer context; over-budget or wrong-size bundles are not offered.

## Catalog and scoring

`src/data/inventory.json` is the canonical seeded seller catalog, with one record per size-specific SKU using the exact inventory fields in `json_formats.md`. Each size is a separate SKU, and each item's `image` contains a filename rather than a URL. The frontend resolves those filenames to image assets. Presentation tags such as fit, style, and menswear grouping live separately in `src/data/product-meta.json`; they do not add fields to the wire inventory schema.

Mock buyer ratings use the contract's `probability` from 0 to 1: an illustrative chance of buying that bundle at that price. These are preset demo estimates, not calibrated predictions from a model, and they do not need to sum to 1. The visible price, fit, and style scores are auxiliary explanations; they are separate from the purchase-probability field. The seller analysis uses the ratings to explain what to keep or drop before proposing one final offer.

## Deploy on Vercel

Set the Vercel project's **Root Directory** to `frontend`, use the Vite preset, build with `npm run build`, and serve `dist`. This folder's `vercel.json` contains the standalone frontend configuration. The repository's existing root configuration and backend files are unchanged.

The optional `deployment/vercel.integrated.json` is a future combined-deployment template; it is not active and does not replace the root configuration.

## Demo boundaries

Agent activity, ratings, and analysis are simulated locally. `localStorage` and `BroadcastChannel` synchronize the workspaces on the same browser profile and origin. The JSON catalog is a local data file, not a hosted database. No buyer, seller, middleman, or model API is connected by this frontend.

There is no authentication, payment, shipment, or live calendar/email/weather connection. Preset role buttons enter demo accounts. Catalog prices, tags, and stock are demo data; product photography is illustrative. See `ASSET-CREDITS.md` for sources and `FRONTEND-INTEGRATION.md` for the backend handoff.


