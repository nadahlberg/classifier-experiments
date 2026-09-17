---
name: estimate-infra-cost
description: Estimate the monthly cost of the deploy by reading infra/ and looking up current provider prices
---

# Estimate infra cost

Read `infra/__main__.py` and list every resource that costs money — managed
databases, cluster node pools, load balancers, buckets, registries, and
anything else with a size or tier slug.

Look up the current price for each one on the provider's public pricing
pages (web search); do not quote prices from memory.

Give the user a table breaking down the estimated monthly cost per
resource, with a total. Note anything usage-based (bandwidth, storage
overage) as such rather than guessing a number.

Some costs depend on env vars read by the infra code (e.g. a tier,
resource size, or replica count chosen at deploy time). For each of those, don't pick one value — show the
price at each plausible setting and give the total as a range.
