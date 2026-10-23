---
collection: workload_requirements
doc_id: workload_matlab
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## MATLAB / Simulink
MATLAB is CPU- and RAM-intensive for large matrix operations and simulations; Simulink models can also become
memory-heavy. 16GB RAM is a reasonable baseline for coursework-scale models, 32GB for larger simulations or
running multiple MATLAB sessions. Certain toolboxes (Parallel Computing Toolbox, Deep Learning Toolbox with
GPU acceleration) can use a CUDA-capable NVIDIA GPU to speed up computation — if GPU acceleration is a
requirement, verify the specific MATLAB toolbox's supported GPU list rather than assuming any NVIDIA GPU works.
A multi-core CPU benefits parallelized toolbox functions.
