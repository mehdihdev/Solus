+++
title = "Cross-compilation: the build machine, the target machine, and what the toolchain must be told"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/build_and_toolchain/jetpack-cuda-version-coupling", "corpus:software/build_and_toolchain/python-environments-and-pinning"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "CMake documentation: cmake-toolchains(7), CMAKE_TOOLCHAIN_FILE, CMAKE_SYSROOT", author = "Kitware", identifier = "cmake-toolchains(7)", url = "https://cmake.org/" },
  { title = "GCC manual: ARM options (-mcpu, -mfpu, -mfloat-abi) and target triplets", author = "GNU Project", identifier = "GCC manual", url = "https://gcc.gnu.org/" },
  { title = "Zephyr Project documentation: toolchains and board definitions", author = "Zephyr Project", identifier = "Zephyr docs", url = "https://docs.zephyrproject.org/" },
]
+++

Cross-compiling means building on one machine (the host, usually your x86-64 laptop) code that will run on another (the target: an ARM Cortex-M microcontroller, an aarch64 Jetson or Raspberry Pi). Three things differ between them, and each must be told to the build explicitly, because the compiler's defaults all describe the host.

1. The compiler itself. A cross toolchain is named by its target triplet: `arm-none-eabi-gcc` for bare-metal 32-bit ARM with no OS (STM32, nRF52, RP2040), `aarch64-linux-gnu-gcc` for 64-bit ARM Linux. The prefix is the target; `gcc` with no prefix builds for the host. Using the wrong one produces a binary the target cannot load or, on bare metal, one that faults at reset.

2. The CPU and ABI flags. Within one triplet the toolchain still needs the exact core and floating-point ABI (for a Cortex-M4F, something like `-mcpu=cortex-m4 -mfpu=fpv4-sp-d16 -mfloat-abi=hard`). Mixing objects or libraries built with different float ABIs is a link error at best and silently wrong argument passing at worst. Vendor SDKs and Zephyr derive these from the board definition; check them whenever you bring in a prebuilt library.

3. The sysroot: the target's headers and libraries. For Linux targets the build must resolve includes and link against the target's libc, not the host's. CMake handles this with a toolchain file (`-DCMAKE_TOOLCHAIN_FILE=...`) that sets `CMAKE_SYSTEM_NAME`, `CMAKE_SYSTEM_PROCESSOR`, the compilers, and `CMAKE_SYSROOT`, so that `find_package` cannot pick up a host library by accident.

Practical consequences for a robot team:

- "It builds on my laptop" is not evidence for the target. Build for the target in CI with the same toolchain file or container image the deploy uses.
- On a Jetson or Pi it is often simpler to build natively on the device (or in an aarch64 container under emulation) than to maintain a full sysroot; the trade is build time.
- Python packages with compiled extensions are cross-compiled too, implicitly: a wheel is per platform and per Python version, and one downloaded for x86-64 will not import on aarch64.
- Bare-metal targets additionally need a linker script (the flash and RAM layout) and start-up code. These come from the vendor SDK and are per part number, not per family.
