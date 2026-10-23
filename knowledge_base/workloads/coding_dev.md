---
collection: workload_requirements
doc_id: workload_coding_dev
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Coding / software development (VS Code, general IDEs)
Modern code editors and IDEs are not heavy on GPU, but compiling, running local dev servers, and multiple
extensions add up. Recommended baseline: 16GB RAM (8GB is workable for light scripting but tight with a
browser and Docker open simultaneously), a fast NVMe SSD (project checkouts, node_modules, and language
servers are I/O-heavy), and a CPU with decent multi-core performance for parallel builds/tests. A discrete GPU is
not required unless the workload also includes ML/DL or graphics work. A comfortable keyboard, a matte/anti-glare
display, and good battery life matter more here than raw GPU power for most day-to-day coding.
