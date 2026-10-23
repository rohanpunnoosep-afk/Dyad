# Clothing agent marketplace — demo overview

Team review draft · Target duration: three minutes

## Overview

The marketplace connects a buyer agent with a seller agent to assemble clothing bundles around the buyer's preferences and the seller's inventory and pricing limits. The buyer receives five options scored on price, fit, and style, chooses one, and completes the deal through seller acceptance and a final buyer confirmation.

The demo runs in two windows of the same browser, with a buyer workspace in one and a seller workspace in the other. Role buttons open preset accounts, and shared browser state keeps both views synchronized. No passwords or external integrations are required.

## Workflow

The demo buyer shops for menswear. They begin by selecting **Casual** and **Athletic** as their broad style preferences. The next section displays outfit images based on those selections, and the buyer chooses three loungewear-style looks to make their preferences more specific.

A short text conversation then narrows down location, likely occasions, and any remaining details such as size, preferred fit, and budget. Location provides context for climate-appropriate clothing. The image selections and chat answers become a compact buyer profile that they can review before connecting to the seller.

The seller opens a prepopulated clothing catalog containing enough loungewear to support several different bundles, alongside streetwear, athletic, casual, and formal items. They configure a few rules, such as the maximum number of items per bundle and the maximum discount from base prices, then make their agent available.

When the buyer clicks **Connect**, the agents exchange the buyer's requirements and seller proposals. Brief activity updates make the exchange visible. The seller agent assembles five distinct bundles within its rules, and the buyer agent evaluates them against the buyer's profile. A bundle can contain any combination of pieces; it does not have to be a complete outfit.

The buyer receives a five-bundle report showing the included products, sizes, total prices, and separate scores for price, fit, and style. Each bundle also has a holistic match percentage and a short explanation of its tradeoffs. The percentage expresses estimated suitability for that buyer, rather than purchase likelihood. Bundles are evaluated independently, so their percentages do not need to total 100%.

Choosing a bundle sends it to the seller and puts the buyer's view into an awaiting-acceptance state. The seller sees the selected items and price with **Accept** and **Decline** actions. In the happy path, the seller accepts, the buyer sees that acceptance and confirms the bundle, and both windows display the same completed deal.

## Demo boundaries

The frontend may initially use a simulated agent exchange with seeded recommendations. If so, describe it as a demo simulation. A live A2A claim requires an implemented agent connection. Text progress updates show activity summaries, not an agent's internal reasoning.

Location and occasion information comes from the buyer's text input. Calendar, email, and live weather are not connected. Same-browser synchronization supports these two windows; it does not establish cross-device support. No purchase, payment, or shipment occurs.

The session can be reset to restore the starting state for another run.
