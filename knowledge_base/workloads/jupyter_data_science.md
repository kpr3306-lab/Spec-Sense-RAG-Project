---
collection: workload_requirements
doc_id: workload_jupyter_datascience
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Jupyter / Python data science (pandas, NumPy, scikit-learn)
Classic (non-deep-learning) data science work is mostly CPU- and RAM-bound. Loading and manipulating large
CSVs/dataframes in memory benefits heavily from RAM headroom — 16GB is a reasonable minimum, 32GB is
safer for larger datasets. A fast NVMe SSD speeds up dataset loading. A discrete GPU is not required for classic
scikit-learn-style workloads, but becomes important the moment the workload shifts toward deep learning
(see the separate ML/DL requirements). Multi-core CPU performance helps parallelized pandas/NumPy operations.
