---
collection: workload_requirements
doc_id: workload_ml_dl
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Machine learning / deep learning (model training, not just inference)
Local deep-learning training is GPU- and VRAM-bound above almost everything else: VRAM capacity determines
the maximum model/batch size that fits on-device, and an NVIDIA GPU with CUDA support is the practical
requirement for most common frameworks (PyTorch, TensorFlow) to use hardware acceleration smoothly — AMD
GPU support exists but has narrower library compatibility. For anything beyond small models/datasets, 8GB VRAM
is a tight minimum and 12-16GB+ is much more comfortable; many serious training workloads are still better
handled on a cloud GPU instance than a laptop regardless of the laptop's GPU, and a laptop's role is often
prototyping/inference rather than full training runs. System RAM of 32GB+ helps when preprocessing large
datasets in memory. Fast NVMe storage matters for dataset I/O. For on-device inference of small models
(rather than training), a strong NPU (see TOPS in the hardware glossary) can run certain optimized models
efficiently without needing the discrete GPU at all.
