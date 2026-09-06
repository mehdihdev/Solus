+++
title = "pip versus apt on a robot: keep the system Python for ROS, put everything else in a pinned environment"
kind = "rule_of_thumb"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = ["corpus:software/build_and_toolchain/jetpack-cuda-version-coupling", "corpus:software/build_and_toolchain/cross-compilation-basics"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "PEP 668: Marking Python base environments as externally managed", author = "Python Software Foundation", identifier = "PEP 668", url = "https://peps.python.org/" },
  { title = "Python documentation: venv, and Installing Python Modules", author = "Python Software Foundation", identifier = "Python docs", url = "https://docs.python.org/" },
  { title = "ROS 2 documentation: installation from Debian packages and rosdep", author = "Open Robotics / ROS 2", identifier = "ROS 2 docs, Installation", url = "https://docs.ros.org/" },
]
+++

On an Ubuntu robot computer two package managers fight over one Python. apt installs Debian packages (`python3-numpy`, `ros-humble-*`) into the system interpreter and tracks dependencies between them. pip installs from PyPI into whichever interpreter runs it and knows nothing about apt. The classic failure: `sudo pip install numpy` overwrites the apt-managed NumPy that ROS's `cv_bridge` or `sensor_msgs_py` was built against, and ROS nodes start failing with ABI or import errors unrelated to anything you changed. Recent Debian and Ubuntu releases mark the system interpreter externally managed (PEP 668) and refuse a plain `pip install`; the `--break-system-packages` flag does what its name says.

Rules that keep this sane:

- ROS 2 and everything ROS imports come from apt, including via `rosdep install`, which resolves to apt packages. Do not pip-install a newer version of something ROS already provides.
- Application code and its non-ROS dependencies live in a virtual environment (`python -m venv`, `uv`, `poetry`) created from a lock file that pins exact versions and hashes. A `requirements.txt` of bare names is not pinned; `numpy>=1.20` today and next month are different installs.
- Pin the interpreter version too. ROS 2 Humble is built for Ubuntu 22.04's Python 3.10; a venv made with Python 3.12 cannot import the apt-installed `rclpy`, because compiled extensions are per minor version.
- If a venv must see ROS packages, create it with `--system-site-packages` and install nothing in it that shadows an apt-provided module. Otherwise run ROS nodes on the system interpreter and keep the venv for tooling.
- On a Jetson, GPU-accelerated wheels are additionally per JetPack; a lock file resolved on a laptop will not resolve on the device.
- Record the whole environment (OS release, Python version, ROS distro, lock file hash) in the repository. "It imports fine here" means nothing without it.

When Solus reports a Python dependency conflict, first check whether the same module is installed twice (`pip show` for the pip copy, `dpkg -S` on the module path for the apt copy). The fix is to remove the pip copy, not to upgrade the apt one.
