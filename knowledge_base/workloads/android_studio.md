---
collection: workload_requirements
doc_id: workload_android_studio
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## Android Studio / mobile app development
Android Studio itself is RAM- and CPU-hungry, and running an Android emulator alongside it roughly doubles the
memory pressure. 16GB RAM is a workable minimum with a single emulator instance; 32GB is more comfortable for
running the emulator, IDE, and a browser/other tools simultaneously without slowdowns. Hardware virtualization
support (Intel VT-x / AMD-V) is required for emulator acceleration. A fast NVMe SSD noticeably improves Gradle
build times. A discrete GPU is not required unless the app itself does graphics-heavy (e.g. game) development.
