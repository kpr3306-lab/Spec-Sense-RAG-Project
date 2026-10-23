---
collection: workload_requirements
doc_id: workload_docker
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Docker / containerized development
Running multiple containers simultaneously (a typical microservices dev setup: app + database + cache + message
queue) is RAM-hungry, since each container reserves its own memory footprint on top of the host OS and any other
open applications. 16GB RAM is a workable minimum for a handful of light containers; 32GB is recommended for
running a fuller local stack or running Docker alongside a resource-heavy IDE. Fast NVMe storage significantly
improves container image pull/build times. CPU core count helps when running parallel builds or many
simultaneous containers.
