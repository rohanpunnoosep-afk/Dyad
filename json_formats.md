# Brojans JSON formats

Every message between the buyer agent, the middle man and the seller agent is JSON.
The agents never talk directly: every message passes through the middle man, which
parses it, validates it, stores it and forwards it to the next stage.

**Negotiation: single round, 5 bundles** (`BRIEF → PROPOSE → JUDGE → ANALYZE → FINAL → DECIDE → DONE`)

```
1. inventory          (seller's catalog)                 db/seed_items.json, models.schemas.Item
2. context            buyer  -> seller   SSE `brief`      models.schemas.BuyerBrief
3. bundles (5)        seller -> buyer    SSE `bundles_proposed`
4. check              middle man         SSE `check`
5. ratings            buyer  -> seller   SSE `ratings` (+ `heat`)
6. analysis           seller             SSE `analysis`   models.schemas.RoundAnalysis
7. final bundle       seller -> buyer    SSE `final_offer`
8. check              middle man         SSE `check`
9. decision           buyer  -> seller   SSE `decision`
```

Stage pattern: `JSON in -> [prompt + JSON] -> model (OpenAI) -> JSON out -> middle man parses + validates -> next stage`.
If validation fails, the middle man re-prompts the same agent once with the errors.

---

## 1. Inventory item (product)

One JSON per SKU. Each size is its own SKU. Products have no images, only an image *file name*.

```json
{
  "sku": "JKT-01-BR-M",
  "name": "Canvas Jacket",
  "category": "jacket",
  "color": "brown",
  "material": "cotton canvas",
  "size": "M",
  "price": 89,
  "stock": 8,
  "image": "JKT-01-BR-M.jpg"
}
```

| Field | Type | Notes |
|---|---|---|
| `sku` | string | Unique id. Format `CAT-NN-COLOR-SIZE` |
| `name` | string | Display name |
| `category` | string | Product type (jacket, tee, pants, jeans, boots, ...) |
| `color` | string | Main color |
| `material` | string | Main material |
| `size` | string | Single size for this SKU (`M`, `32`, `10`, `OS`) |
| `price` | number | Dollars |
| `stock` | int | Units available. `0` = out of stock, never offered |
| `image` | string | Image file name, always passed along with the item |

Example inventory used in the examples below:

```json
[
  { "sku": "JKT-01-BR-M",  "name": "Canvas Jacket",     "category": "jacket",   "color": "brown",     "material": "cotton canvas",  "size": "M",  "price": 89,  "stock": 8,  "image": "JKT-01-BR-M.jpg" },
  { "sku": "JKT-02-OL-M",  "name": "Chore Jacket",      "category": "jacket",   "color": "olive",     "material": "cotton twill",   "size": "M",  "price": 110, "stock": 5,  "image": "JKT-02-OL-M.jpg" },
  { "sku": "JKT-03-NV-M",  "name": "Nylon Bomber",      "category": "jacket",   "color": "navy",      "material": "nylon",          "size": "M",  "price": 95,  "stock": 6,  "image": "JKT-03-NV-M.jpg" },
  { "sku": "TEE-01-OL-M",  "name": "Heavyweight Tee",   "category": "tee",      "color": "olive",     "material": "cotton",         "size": "M",  "price": 35,  "stock": 20, "image": "TEE-01-OL-M.jpg" },
  { "sku": "TEE-02-WH-M",  "name": "Boxy Tee",          "category": "tee",      "color": "white",     "material": "cotton",         "size": "M",  "price": 30,  "stock": 15, "image": "TEE-02-WH-M.jpg" },
  { "sku": "SHT-01-BL-M",  "name": "Oxford Shirt",      "category": "shirt",    "color": "pale blue", "material": "cotton oxford",  "size": "M",  "price": 68,  "stock": 10, "image": "SHT-01-BL-M.jpg" },
  { "sku": "PNT-01-OL-32", "name": "Ripstop Cargo",     "category": "pants",    "color": "olive",     "material": "cotton ripstop", "size": "32", "price": 75,  "stock": 9,  "image": "PNT-01-OL-32.jpg" },
  { "sku": "JNS-01-IN-32", "name": "Straight Jean",     "category": "jeans",    "color": "indigo",    "material": "denim",          "size": "32", "price": 95,  "stock": 7,  "image": "JNS-01-IN-32.jpg" },
  { "sku": "TRS-01-GR-32", "name": "Pleated Trouser",   "category": "trousers", "color": "grey",      "material": "wool blend",     "size": "32", "price": 98,  "stock": 4,  "image": "TRS-01-GR-32.jpg" },
  { "sku": "BOT-01-BR-10", "name": "Leather Work Boot", "category": "boots",    "color": "brown",     "material": "leather",        "size": "10", "price": 160, "stock": 3,  "image": "BOT-01-BR-10.jpg" },
  { "sku": "SNK-01-WH-10", "name": "Leather Sneaker",   "category": "sneakers", "color": "white",     "material": "leather",        "size": "10", "price": 120, "stock": 6,  "image": "SNK-01-WH-10.jpg" },
  { "sku": "LOF-01-BK-10", "name": "Penny Loafer",      "category": "loafers",  "color": "black",     "material": "leather",        "size": "10", "price": 150, "stock": 2,  "image": "LOF-01-BK-10.jpg" }
]
```

---

## 2. Context (buyer -> seller)

The buyer agent extracts this from the user's images and chat. The seller never sees the
user's images, only this context.

```json
{
  "style": ["workwear", "minimal", "rugged", "heritage", "earthy tones", "relaxed fit", "utility", "understated"],
  "colors_liked": ["brown", "olive"],
  "colors_avoid": ["neon"],
  "sizes": { "top": "M", "bottom": "32", "shoe": "10" },
  "budget": 400,
  "occasion": "weekend casual",
  "notes": ["no graphic prints", "no skinny fits", "must include a jacket"]
}
```

| Field | Type | Notes |
|---|---|---|
| `style` | string[] | Descriptive style keywords, as many as useful: aesthetic, vibe, fit, era (e.g. `"workwear"`, `"rugged"`, `"earthy tones"`, `"relaxed fit"`). The seller builds bundles to match them and the analyst labels items with them where they fit |
| `colors_liked` | string[] | Preferred colors |
| `colors_avoid` | string[] | **Hard rule**: never offered |
| `sizes` | object | Size per slot (`top`, `bottom`, `shoe`). Only matching SKUs are offered |
| `budget` | number | Dollars. **Hard rule**: bundle price must be at or under this |
| `occasion` | string | What it's for |
| `notes` | string[] | **Strictly followed.** The user's explicit rules, word for word. "must include a X" notes are enforced in code (bundle rejected); other notes go to both agents as strict rules, and the buyer rates a bundle that breaks one at 0.1 or lower |

---

## 3. Bundles (seller -> buyer)

Exactly 5 bundles, each 2-5 items, all different from each other so the ratings are informative.

The `bundles_proposed` event. Ids are UUIDs in practice; `b1`... is shorthand here.

```json
{
  "round": 1,
  "bundles": [
    { "id": "b1", "skus": ["JKT-01-BR-M", "TEE-01-OL-M", "PNT-01-OL-32"],                 "images": ["JKT-01-BR-M.jpg", "TEE-01-OL-M.jpg", "PNT-01-OL-32.jpg"],                     "items_total": 199, "price": 179 },
    { "id": "b2", "skus": ["JKT-03-NV-M", "TEE-02-WH-M", "JNS-01-IN-32", "SNK-01-WH-10"], "images": ["JKT-03-NV-M.jpg", "TEE-02-WH-M.jpg", "JNS-01-IN-32.jpg", "SNK-01-WH-10.jpg"], "items_total": 340, "price": 305 },
    { "id": "b3", "skus": ["JKT-02-OL-M", "SHT-01-BL-M", "TRS-01-GR-32", "LOF-01-BK-10"], "images": ["JKT-02-OL-M.jpg", "SHT-01-BL-M.jpg", "TRS-01-GR-32.jpg", "LOF-01-BK-10.jpg"], "items_total": 426, "price": 380 },
    { "id": "b4", "skus": ["JKT-02-OL-M", "TEE-01-OL-M", "PNT-01-OL-32", "SNK-01-WH-10"], "images": ["JKT-02-OL-M.jpg", "TEE-01-OL-M.jpg", "PNT-01-OL-32.jpg", "SNK-01-WH-10.jpg"], "items_total": 340, "price": 309 },
    { "id": "b5", "skus": ["JKT-01-BR-M", "JNS-01-IN-32", "BOT-01-BR-10"],                "images": ["JKT-01-BR-M.jpg", "JNS-01-IN-32.jpg", "BOT-01-BR-10.jpg"],                    "items_total": 344, "price": 315 }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Bundle id |
| `name` | string | Bundle name (also sent, omitted above) |
| `skus` | string[] | Items in the bundle (no repeats) |
| `images` | string[] | Image file names, same order as `skus` |
| `items_total` | number | Sum of item prices. **Computed by code** |
| `price` | number | Bundle price in dollars. Must be 60-105% of `items_total` and at or under `budget` |
| `pitch` | string | Seller's one-line pitch (also sent, omitted above) |

The buyer agent receives the full item JSONs for each SKU when rating.

---

## 4. Check (middle man)

Runs after every seller output (bundles and final).

```json
{ "stage": "bundles", "valid": true, "errors": [], "rejected_attempts": [] }
```

On failure the seller is re-prompted once with the errors. Rejected attempts are listed in the
`check` event that follows the accepted output; if the retry fails too, the negotiation fails
with an `error` event. A rejected attempt's errors look like:

```json
{
  "stage": "bundles",
  "valid": false,
  "errors": [
    "b2: no jacket (breaks note 'must include a jacket')",
    "b4: SKU PNT-01-OL-30 wrong size (bottom is 32)"
  ]
}
```

Checks: valid JSON/schema, bundle count, 2-5 items, SKUs exist, in stock, sizes match `sizes`
(or one size `OS`), no `colors_avoid`, "must include" notes, no repeated SKU, no two identical
bundles, price range, budget, and (final only) no cold or dropped SKUs.

---

## 5. Ratings (buyer -> seller)

```json
{
  "round": 1,
  "ratings": [
    { "id": "b1", "probability": 0.78, "price_score": 0.8, "fit_score": 0.9, "style_score": 0.85, "reason": "Brown jacket + olive tee and cargo: exact palette and workwear style" },
    { "id": "b2", "probability": 0.41, "reason": "Navy bomber and white sneakers feel sporty, not workwear" },
    { "id": "b3", "probability": 0.15, "reason": "Oxford, wool trousers and loafers are too formal for weekend casual" },
    { "id": "b4", "probability": 0.64, "reason": "All-olive works, but white sneakers break the workwear look" },
    { "id": "b5", "probability": 0.72, "reason": "Brown jacket + boots are strong; jeans fine" }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | Bundle id being rated |
| `probability` | number 0-1 | Chance the buyer buys this bundle at this price. 0.5 = coin flip. A broken note means 0.1 or lower |
| `price_score` / `fit_score` / `style_score` | number 0-1 | Sub-scores behind the probability (sent for every bundle, shown once above) |
| `reason` | string | Names the specific items that help or hurt |

Followed by a `heat` event: every SKU's score = mean probability of the bundles containing it
(`hot` ≥ 0.6, `cold` ≤ 0.3). Cold SKUs can never be in the final bundle.

```json
{ "round": 1, "items": [ { "sku": "JKT-01-BR-M", "score": 0.75, "label": "hot", "bundle_count": 2 } ] }
```

---

## 6. Analysis (seller: what works / what doesn't)

The seller checks every rating. For each bundle rated **below 0.5**, it inspects each item
(per-item inference), then compares those inferences against the collective attribute
averages. Something is a `confirmed` issue only when both agree.

```json
{
  "round": 1,
  "avg": 0.54,
  "subscore_avgs": { "price": 0.71, "fit": 0.84, "style": 0.5 },
  "attribute_avgs": {
    "category": { "boots": 0.72, "pants": 0.71, "sneakers": 0.53, "loafers": 0.15, "trousers": 0.15, "shirt": 0.15 },
    "color":    { "brown": 0.75, "olive": 0.52, "white": 0.53, "navy": 0.41, "pale blue": 0.15, "grey": 0.15, "black": 0.15 },
    "material": { "leather": 0.49, "cotton canvas": 0.75 },
    "size":     { "m": 0.54, "32": 0.54, "10": 0.49 },
    "style":    { "workwear": 0.72, "minimal": 0.53, "sporty": 0.41, "formal": 0.15 }
  },
  "item_checks": [
    { "bundle_id": "b2", "sku": "JKT-03-NV-M",  "verdict": "hurts", "dimension": "style", "note": "Sporty bomber" },
    { "bundle_id": "b2", "sku": "SNK-01-WH-10", "verdict": "hurts", "dimension": "style", "note": "Sporty" },
    { "bundle_id": "b3", "sku": "SHT-01-BL-M",  "verdict": "hurts", "dimension": "style", "note": "Formal" },
    { "bundle_id": "b3", "sku": "TRS-01-GR-32", "verdict": "hurts", "dimension": "style", "note": "Formal" },
    { "bundle_id": "b3", "sku": "LOF-01-BK-10", "verdict": "hurts", "dimension": "style", "note": "Formal" }
  ],
  "works": [
    { "type": "color",    "value": "brown", "avg_prob": 0.75, "votes": 0, "confirmed": false },
    { "type": "category", "value": "boots", "avg_prob": 0.72, "votes": 0, "confirmed": false },
    { "type": "category", "value": "pants", "avg_prob": 0.71, "votes": 0, "confirmed": false }
  ],
  "fails": [
    { "type": "style", "value": "formal", "avg_prob": 0.15, "votes": 3, "confirmed": true },
    { "type": "style", "value": "sporty", "avg_prob": 0.41, "votes": 2, "confirmed": true }
  ],
  "keep_skus": ["JKT-01-BR-M", "TEE-01-OL-M", "PNT-01-OL-32", "BOT-01-BR-10"],
  "drop_skus": ["JKT-03-NV-M", "SNK-01-WH-10", "SHT-01-BL-M", "TRS-01-GR-32", "LOF-01-BK-10"],
  "main_issue": "style"
}
```

| Field | Type | Source | Notes |
|---|---|---|---|
| `round` | int | code | Always 1 for now |
| `avg` | number | code | Mean probability across the 5 bundles |
| `subscore_avgs` | object | code | Mean of the buyer's price / fit / style sub-scores |
| `attribute_avgs` | object | code | Per category/color/material/size value: mean probability of bundles containing it (a value counts once per bundle). `style` uses the seller analyst's style label for each SKU |
| `item_checks[]` | array | model | One entry per item in each bundle rated < 0.5. Entries for other bundles, unknown SKUs or duplicates are dropped |
| `item_checks[].verdict` | `hurts` \| `neutral` \| `helps` | model | |
| `item_checks[].dimension` | `category` \| `style` \| `color` \| `material` \| `size` \| `price` \| `none` | model | Why it hurts |
| `works[]` / `fails[]` | array | model + code | Attribute values pulling ratings up / down |
| `fails[].votes` | int | code | How many `hurts` item checks blamed this dimension on an item with this value |
| `fails[].confirmed` | bool | code | `votes > 0` and `avg_prob` below the round `avg`. For price/fit (no per-item value) it uses the matching sub-score average < 0.5 instead |
| `keep_skus` / `drop_skus` | string[] | model + code | Only SKUs from this round. Cold SKUs are always added to `drop_skus`. `drop_skus` are banned from the final |
| `main_issue` | string | model | The dimension most responsible for low ratings |

---

## 7. Final bundle (seller -> buyer)

Exactly 1 bundle, built from the analysis (best bundle improved with `keep_skus`, no `drop_skus`).

The `final_offer` event. `items` carries the full product JSON of each SKU.

```json
{
  "final": {
    "id": "final",
    "name": "Workwear Core+",
    "skus": ["JKT-01-BR-M", "TEE-01-OL-M", "PNT-01-OL-32", "BOT-01-BR-10"],
    "images": ["JKT-01-BR-M.jpg", "TEE-01-OL-M.jpg", "PNT-01-OL-32.jpg", "BOT-01-BR-10.jpg"],
    "items_total": 359,
    "price": 319,
    "savings": 40,
    "why": "Best bundle (b1, 0.78) + boots from b5 (0.72); no formal or sporty pieces"
  },
  "items": [ { "sku": "JKT-01-BR-M", "name": "Canvas Jacket", "...": "full product JSON" } ]
}
```

| Field | Type | Notes |
|---|---|---|
| `items_total` | number | **Computed by code** |
| `savings` | number | `items_total - price`. **Computed by code** |
| `why` | string | Seller's reasoning, referencing the ratings/analysis |

The middle man runs the same check (section 4) with `"stage": "final"`.

---

## 8. Decision (buyer -> seller)

The `decision` event (`id` is the final bundle's id; ids are UUIDs in practice):

```json
{ "id": "final", "decision": "accept", "probability": 0.88, "reason": "Follows all notes, matches style and colors, $81 under budget" }
```

| Field | Type | Notes |
|---|---|---|
| `decision` | `accept` \| `reject` | |
| `probability` | number 0-1 | Buy probability for the final bundle |
| `reason` | string | Why |

---

## Rules summary

- Prices are dollars everywhere.
- `notes`, `colors_avoid`, `sizes` and `budget` are hard rules, enforced by the middle man, not just the prompt.
- Only in-stock SKUs (`stock > 0`) are offered.
- Every item reference carries its `image` file name.
- Fields marked "computed by code" are never trusted from the model's output; the middle man recalculates them.
