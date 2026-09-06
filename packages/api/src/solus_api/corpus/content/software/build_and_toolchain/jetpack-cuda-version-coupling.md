+++
title = "On Jetson, CUDA comes from JetPack: you cannot pick the CUDA version independently"
kind = "pitfall"
audience = "reference"
applicability = [{ key = "mcu_family", value = "jetson" }]
derivation = "solus_original"
confidence = 0.8
confidence_basis = "vendor_stated"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/build_and_toolchain/cross-compilation-basics", "corpus:software/build_and_toolchain/python-environments-and-pinning"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "NVIDIA JetPack SDK documentation and release notes (component versions per JetPack release)", author = "NVIDIA", identifier = "JetPack SDK docs", url = "https://docs.nvidia.com/" },
  { title = "NVIDIA Jetson developer pages: JetPack, Jetson Linux (L4T), and PyTorch for Jetson", author = "NVIDIA", identifier = "Jetson developer pages", url = "https://developer.nvidia.com/" },
]
+++

On a desktop you install a GPU driver and then any CUDA toolkit that driver supports. On an NVIDIA Jetson it does not work that way. JetPack is a single release that bundles the board support package (Jetson Linux, "L4T": kernel, bootloader, drivers) with a specific CUDA toolkit and matching cuDNN, TensorRT, and multimedia libraries. The CUDA version is fixed by the JetPack you flashed, because the GPU driver lives inside L4T and the CUDA runtime must match it.

Consequences:

- You cannot `apt install` or `pip install` your way to a different CUDA major version on a given JetPack. Changing CUDA means reflashing to a different JetPack, which also changes the kernel and the Ubuntu release.
- Every GPU-accelerated package (PyTorch, torchvision, TensorFlow, ONNX Runtime, OpenCV with CUDA) must be a build for your exact JetPack and CUDA pair. Generic wheels from PyPI are x86-64 or CPU-only aarch64 and will either fail to install or run with `torch.cuda.is_available()` returning false. NVIDIA publishes Jetson-specific wheels and containers per JetPack; use those.
- The major steps have been large: the JetPack 4 line shipped CUDA 10.x, JetPack 5 moved to CUDA 11.x, and JetPack 6 to CUDA 12.x. A library that says "needs CUDA 12" therefore implies a JetPack 6 image, which implies a module JetPack 6 supports (the Orin family; the original Nano and the TX2 stopped at JetPack 4). Check the JetPack release notes for exact minor versions and supported modules before committing to a platform rather than trusting memory or a forum post.

How to find out what a board actually has: `cat /etc/nv_tegra_release` (L4T release), `dpkg -l nvidia-jetpack` (JetPack metapackage), `nvcc --version` or `/usr/local/cuda/version.json` (CUDA), and `python3 -c "import torch; print(torch.version.cuda)"` to confirm the framework agrees. Record all four in the project so a "works on my Jetson" bug can be reproduced.

Solus flags a mismatch when a project declares a Jetson target and a dependency pins a CUDA version the declared JetPack cannot supply. The fix is almost always to change the dependency version, not the JetPack.
