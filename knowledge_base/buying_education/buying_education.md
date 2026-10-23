---
collection: buying_education
doc_id: buying_education_pitfalls
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## "More GHz" doesn't mean "faster" across different CPU generations or brands
Clock speed (GHz) is only comparable within the same CPU architecture/generation. A newer-generation chip at a
lower clock speed can outperform an older chip at a higher clock speed because of architectural efficiency
improvements. Compare benchmark results or the same-generation model numbers, not raw GHz across brands
or generations.

## Same GPU model name, different real-world performance
The same discrete GPU model (e.g. "RTX 4060") can be configured at different power limits (TGP) in different
laptop chassis. A thin, quiet laptop with a lower TGP configuration of a given GPU will perform noticeably below
a bulkier gaming laptop using the same GPU model at a higher TGP. Always check the configured wattage where
available, not just the GPU model name.

## Advertised battery life vs. real-world battery life
Manufacturer-advertised battery hours are measured under specific, often best-case conditions (low brightness,
airplane mode, idle/video-playback loops). Real-world battery life with normal brightness, Wi-Fi, and active use
is typically lower. Where available, independent test results are a more reliable comparison point than the
advertised number, and battery Wh capacity is a useful sanity-check figure on its own.

## Soldered RAM/storage vs. upgradeable
Many thin-and-light laptops solder RAM (and sometimes even storage) directly to the motherboard for space and
power reasons — this cannot be upgraded later. If future upgradeability matters, check "soldered vs. SO-DIMM"
for RAM and confirm whether there's a spare M.2 slot for storage before buying, rather than assuming it can be
added later.

## Screen size vs. weight vs. portability trade-off
Larger screens (16"+) generally mean a heavier, bulkier chassis and often a bigger battery to offset higher power
draw; very light laptops (under ~1.4kg) usually have smaller screens or make other trade-offs (fewer ports, smaller
battery). There's no "best" choice here — it depends on whether portability or screen real estate matters more for
the buyer's actual daily use.

## Marketing terms that need translation
"AI PC" generally refers to a laptop with a dedicated NPU meeting a minimum TOPS threshold for certain OS-level
AI features — it does not by itself indicate strong general performance or GPU capability. "Creator laptop" usually
implies a colour-accurate display and a capable GPU but isn't a standardized spec tier. Always translate marketing
labels back into the underlying hard specs (NPU TOPS, GPU model + VRAM + TGP, display gamut coverage, etc.)
rather than relying on the label alone.

## When no laptop satisfies every constraint
For tight, unusual combinations of hard constraints (e.g. very low weight + high RAM + long battery life + low
budget), it's common for zero or very few products to satisfy every requirement simultaneously. The honest
response is to say so explicitly and present the closest compromises with a clear explanation of which
constraint(s) had to be relaxed and why — not to silently drop a requirement or quietly recommend something
that doesn't actually meet it.
