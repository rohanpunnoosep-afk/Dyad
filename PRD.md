# Clothing agent marketplace — quick PRD

Status: team review draft · October 16, 2026

## Product

A buyer agent and a seller agent work together to assemble clothing bundles tailored to a buyer. The buyer supplies style preferences, sizing, budget, likely occasions, and location. The seller supplies a tagged inventory and limits on what its agent may offer. The agents exchange proposals, and the buyer receives five bundles to compare.

The product focuses on the fit of the whole bundle to the buyer's needs, rather than choosing individual products in isolation. A bundle can contain any combination of clothing pieces; it does not have to be a complete outfit.

## Hackathon scope

Build a polished, three-minute happy-path demo hosted on Vercel. Two windows in the same browser represent a buyer and a seller. Role buttons open preset accounts; passwords and authentication are out of scope. Shared browser state synchronizes the two windows for this demo. This does not provide cross-device persistence.

The intended demo buyer is a man seeking minimalistic loungewear. Onboarding remains interactive, but its defaults, available demo responses, and resulting recommendations support that scenario. Seller inventory must contain enough relevant items for five distinct bundles and enough other styles to look like a general clothing catalog.

## Buyer experience

1. Click **Enter as buyer**.
2. Select outfit imagery from a style grid. Styles include surf/skate, urban/street, country club, athletic, lounging, casual, business casual, and formal. The demo selects lounging.
3. Refine the preference toward minimal or distinctive styling. The demo selects minimal.
4. Provide budget, sizes, and fit preferences through concise controls. Collect likely occasions and location through a short text conversation. Exact demo values remain to be agreed.
5. Review a compact buyer profile summarizing style, budget, size, fit, occasions, and location.
6. Click **Connect** to start the exchange with the seller agent.
7. See brief progress updates, then a report containing exactly five bundles.
8. Compare bundles and select one. This sends a proposal to the seller; it does not complete the deal.
9. After seller acceptance, review and confirm the bundle to complete the demo.

Location is preference context for climate-appropriate fabrics and local style. No live weather, email, or calendar integration is required. The interface must not imply that those sources were connected or checked.

## Seller experience

1. Click **Enter as seller**.
2. See a prepopulated inventory dashboard with product imagery, prices, and tags.
3. Set a few agent rules, including maximum items per bundle and maximum discount from base prices.
4. Make the seller available for the buyer connection.
5. See an incoming selection containing the chosen bundle, price, and buyer match summary.
6. Click **Accept** or **Decline**. The demonstrated path uses Accept.
7. See the completed deal after the buyer's final confirmation.

Seller-generated bundles should already satisfy the seller's rules. The final seller acceptance remains an explicit step in the demo, even though every offered bundle is acceptable under those rules.

## Five-bundle report

Each bundle shows:

- Included products, images, selected sizes, and fit details.
- Base total, offered total, and any discount.
- **Price score:** alignment with the buyer's budget and value preferences.
- **Fit score:** alignment with size and preferred cut or silhouette.
- **Style score:** alignment with the buyer's visual preferences and intended occasions.
- A holistic match percentage and a short explanation of the tradeoffs.
- A clear **Choose this bundle** action.

The percentage represents estimated suitability, not purchase likelihood. Each bundle is scored independently; percentages do not need to total 100%. The UI should call it **Match**, rather than implying a statistically calibrated probability. Score weighting and calculation are still open; any scripted values are demo estimates.

## Inventory and shared state

Minimum product fields: ID, name, image, category, mens/womens designation, available sizes, fabric composition, fit, style tags, base price, and available quantity.

Fabric tags include cotton, polyester, and silk. Fit tags include loose, tight, baggy, flared, and regular. Core menswear style tags include urban/street, athletic, casual, and formal; add lounging/loungewear so the demo scenario is represented directly.

Seed multiple compatible loungewear tops and bottoms across sizes, fits, fabrics, and prices. Add a visible supporting selection of streetwear, athletic, everyday casual, and formal clothing. Five bundles must have different product combinations, use available sizes, and respect seller rules.

Shared session data includes buyer profile, seller availability and rules, connection status, five bundle proposals, selected bundle, seller decision, and buyer confirmation. Keep the role local to each window so opening the seller view does not change the buyer window's role.

Deal states: **setup → ready → negotiating → bundles ready → awaiting seller → awaiting buyer confirmation → completed**. Seller decline leads to a declined state with a return to bundle selection. Prevent duplicate submissions and decisions on an outdated selection.

## Agent exchange and implementation boundary

The intended architecture uses an A2A framework to exchange buyer requirements, seller proposals, and buyer evaluations. The seller offers five bundles; the buyer agent scores price, fit, and style and returns those evaluations before presenting the report. Any further negotiation rounds are outside the required demo path.

The first frontend version may simulate that exchange and use seeded inventory and scores. Show short activity summaries such as “Sharing buyer preferences,” “Assembling bundles,” and “Comparing price, fit, and style.” Do not present private reasoning or claim a live A2A connection unless it is implemented. The framework, backend contract, and scoring implementation remain team decisions.

## Design

Simple marketplace presentation with strong product imagery, restrained typography, solid colors, and clear status changes. No gradients, generic AI filler, lengthy chat transcripts, or decorative agent jargon. Keep buyer and seller actions obvious when the windows are shown side by side.

## Acceptance criteria

- The full happy path can be demonstrated in about three minutes.
- Buyer and seller views run independently in two same-browser windows and share updates without manual refresh.
- Buyer onboarding produces a reviewable minimalistic-loungewear profile.
- Seller inventory visibly includes both relevant loungewear and other clothing styles.
- Connect produces five distinct, valid bundles after a brief visible exchange.
- All bundles show price, fit, style, and holistic match scores.
- Buyer selection appears in the seller window; seller acceptance appears in the buyer window.
- Completion occurs only after the buyer's final confirmation.
- Seller decline is available and produces a clear recoverable state.
- A reset clears the shared demo session so the presentation can be repeated.

## Out of scope

Real authentication, payments, checkout, fulfillment, live calendar/email/weather access, real marketplace integrations, cross-device synchronization, and production-grade inventory reservation.

## Decisions still open

Product name, exact buyer budget/sizes/location, initial seller rule values, scoring weights, A2A framework, and whether the final presentation uses simulated or live agent responses. These should not block review of the flow.
