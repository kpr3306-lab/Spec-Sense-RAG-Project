---
collection: workload_requirements
doc_id: workload_blender
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Blender / 3D modelling and rendering
Viewport modelling performance depends on GPU and VRAM; final rendering (especially with Cycles' GPU render
mode) is heavily GPU- and VRAM-bound — larger, more detailed scenes need more VRAM headroom (6GB is a tight
minimum for hobbyist scenes, 8GB+ is safer for more complex work). A discrete NVIDIA GPU is generally preferred
since Blender's GPU-accelerated denoising and CUDA/OptiX rendering are NVIDIA-optimized, though AMD GPUs
are also supported via HIP. System RAM of 16-32GB helps with complex scenes and simultaneous background
tasks. A high-refresh, colour-accurate display is a soft-preference plus, not a hard requirement.
