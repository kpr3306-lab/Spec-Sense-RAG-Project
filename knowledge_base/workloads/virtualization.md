---
collection: workload_requirements
doc_id: workload_virtualbox_vms
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Virtual machines (VirtualBox, VMware, Hyper-V)
Each running VM needs its own allocated RAM slice on top of the host OS, so total system RAM should comfortably
exceed (host OS + sum of all VM RAM allocations). Running one Windows or Linux VM alongside normal host use
generally wants 16GB+ system RAM; running multiple VMs simultaneously, or VMs with GUI desktops, pushes that
to 32GB. CPU virtualization extensions (Intel VT-x / AMD-V, present on essentially all modern CPUs) are required
and should be confirmed enabled in BIOS. Fast NVMe storage matters for VM disk-image performance. A high core
count helps when VMs are CPU-intensive themselves (e.g. running builds inside the VM).
