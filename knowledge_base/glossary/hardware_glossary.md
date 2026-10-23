---
collection: hardware_glossary
doc_id: glossary_hardware
source_type: internal_authored
source_date: 2026-09-24
last_verified_date: 2026-09-24
confidence: medium
---

## CPU naming (Intel and AMD)
Processor model names encode generation and tier but not raw speed on their own. Intel's "Core Ultra 5/7/9"
line (Meteor Lake / Lucid Lake generations onward) replaces the old "Core i5/i7/i9" naming for many AI-PC
laptops and adds an on-chip NPU. AMD's "Ryzen 5/7/9" series uses a suffix ("HS", "HX", "U") to indicate power
class: "U" suffixes are low-power (thin-and-light laptops), "HS" are balanced performance-per-watt parts, and
"HX" are unlocked, desktop-class high-performance parts for gaming/workstation laptops. Two chips with the
same tier number (e.g. "Ryzen 7") can differ substantially in core count, clock speed and power draw depending
on the suffix and generation — always compare the exact model string, not just the tier number.

## Cores vs. threads
A CPU core is a physical processing unit. A thread is a stream of instructions a core can work on. Many modern
CPUs use simultaneous multithreading (Intel Hyper-Threading, AMD SMT) so each physical core can handle two
threads at once — hence "threads" often shows as double the core count. More cores/threads generally help
multitasking, compiling, and workloads that parallelize well (video encoding, 3D rendering); they help less for
tasks that are mostly single-threaded (many everyday apps, some games).

## Performance and efficiency cores (P-cores / E-cores)
Recent Intel CPUs mix "Performance" cores (fast, higher power) with "Efficiency" cores (slower, low power) in
one chip — a hybrid architecture. The OS scheduler assigns background/light tasks to E-cores and demanding
tasks to P-cores, improving battery life without sacrificing peak performance. AMD's equivalent, when present,
is a similar big.LITTLE-style split in some mobile parts.

## TDP vs. TGP (power figures)
TDP (Thermal Design Power) describes how much heat a CPU is designed to dissipate under sustained load —
it's a proxy for sustained power draw, not a hard limit; laptop makers can configure the same chip to run at
different sustained power levels ("configurable TDP") depending on cooling design. TGP (Total Graphics Power)
is the GPU equivalent, and many discrete laptop GPUs also have a "Dynamic Boost" range, so the same GPU
model can perform quite differently between two laptops depending on how much TGP headroom the chassis
allows. Never assume performance parity between two laptops just because they share a CPU or GPU model
name — check the configured power limits if available.

## NPU and TOPS
An NPU (Neural Processing Unit) is dedicated silicon for running AI/machine-learning inference efficiently,
separate from the CPU and GPU. TOPS (Trillion Operations Per Second) is the metric used to describe NPU (and
sometimes combined platform) AI throughput. Higher TOPS enables more or faster on-device AI features (background
blur, live captions/translation, local small-model inference) without draining the battery as fast as running the
same workload on the CPU/GPU. TOPS numbers from different vendors are not always measured the same way, so
treat cross-brand comparisons with some caution.

## RAM: capacity, type, and speed
RAM capacity affects how many applications/browser tabs/VMs you can keep open smoothly. RAM type (DDR4,
DDR5, LPDDR5, LPDDR5x) affects bandwidth and power efficiency; LPDDR variants are common in thin-and-light
laptops and are almost always soldered to the motherboard (not upgradeable), while DDR4/DDR5 SO-DIMM RAM
is often user-upgradeable up to the laptop's documented maximum. For multitasking-heavy or VM-heavy workloads,
both capacity and upgradeability matter — check "soldered vs. SO-DIMM" before assuming you can add RAM later.

## SSD: capacity, type, and PCIe generation
SSD capacity is straightforward storage space. SSD type (NVMe vs. older SATA) and PCIe generation (Gen3 vs.
Gen4 vs. Gen5) determine read/write speed — PCIe Gen4 NVMe drives are roughly twice as fast as Gen3 for
sequential transfers, which matters for large dataset loading, video editing scrubbing, and OS/app responsiveness.
The number of M.2 slots determines whether a second drive can be added later.

## Display terms
- **Resolution**: pixel grid (e.g. 1920x1080 "FHD", 2560x1600 "QHD+"). Higher resolution gives sharper text/images
  but costs more GPU power to drive and more battery.
- **Panel type**: IPS and OLED are the common laptop types. OLED gives true blacks and higher contrast but can be
  more prone to long-term burn-in with static content; IPS is generally more burn-in resistant and often cheaper.
- **Refresh rate**: how many times per second the screen redraws (60Hz standard; 90/120/144/240Hz are "high
  refresh", mainly valuable for gaming and very smooth scrolling).
- **Brightness (nits)**: higher nits help outdoor/bright-room visibility.
- **Colour gamut** (sRGB / DCI-P3 / Adobe RGB, given as a percentage of coverage): relevant for photo/video/design
  work where colour accuracy matters; less relevant for general use or gaming.

## Battery: Wh vs. advertised hours
Battery capacity in watt-hours (Wh) is a fixed, comparable physical number. Advertised "battery life in hours" is a
manufacturer claim under specific test conditions (often lower brightness, no background apps) and should not be
compared directly across brands without knowing the test methodology — independent, real-world battery tests are
more reliable for comparison than manufacturer-claimed hours.

## Ports and connectivity
- **USB-A** vs **USB-C**: USB-C is reversible and increasingly used for both data and charging; USB-A is the older
  rectangular connector still needed for many existing peripherals.
- **Thunderbolt / USB4**: a USB-C port with extra capability — higher data speed, external GPU support, and
  driving high-resolution external displays. Not all USB-C ports support this; check for the explicit label.
- **HDMI version** determines maximum resolution/refresh rate for an external display; newer versions (2.1) support
  higher resolutions and refresh rates than older (1.4).
- **Wi-Fi generation** (Wi-Fi 5 / 6 / 6E) and **Bluetooth version** affect wireless speed, latency, and congestion
  handling; Wi-Fi 6E adds the 6GHz band for less-crowded connections where supported.

## Thermals and sustained performance
Peak (burst) performance numbers are less useful than sustained performance under real workloads, because
laptops throttle (reduce clock speed) once they hit thermal limits. Cooling design (heat pipes, vapor chambers, fan
count) determines how long a laptop can hold peak performance before throttling. Independent sustained-load
testing (e.g. running a benchmark for 30+ minutes) is a better predictor of real-world performance for demanding,
long-running tasks than a short burst benchmark score.
