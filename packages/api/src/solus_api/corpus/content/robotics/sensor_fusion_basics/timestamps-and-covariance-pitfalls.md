+++
title = "Timestamps at capture, clocks that agree, and covariances that mean something"
kind = "pitfall"
audience = "reference"
applicability = []
derivation = "solus_original"
confidence = 0.9
confidence_basis = "standard_derived"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/sensor_fusion_basics/covariance-as-trust",
]
further_reading = []
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "REP 145: Conventions for IMU Sensor Drivers", author = "Open Robotics", identifier = "REP 145", url = "https://www.ros.org/reps/rep-0145.html" },
  { title = "sensor_msgs/Imu and geometry_msgs/PoseWithCovariance message definitions", author = "Open Robotics", url = "https://docs.ros.org/" },
  { title = "robot_localization documentation, covariance and sensor timing guidance", author = "Open Robotics", url = "https://docs.ros.org/" },
]
+++

A fusion filter is a machine for combining measurements taken at known times with stated uncertainties. When either the time or the uncertainty is wrong, the filter does not complain; it produces a confident, smooth, wrong answer. These are the ways it usually goes wrong.

Timestamps taken on arrival rather than at capture. A camera frame exposed at time t arrives tens of milliseconds later; a serial IMU packet arrives after buffering. If the driver stamps the message when it reads it, every measurement is shifted late by a variable amount, and a fast-moving robot fuses a pose from where it was with an IMU reading from where it is. Stamp at exposure or sampling time, using hardware triggers or the sensor's own timestamp where available, and measure the offset once if you cannot.

Clocks that disagree. An IMU on a microcontroller, a camera on a compute board, and a lidar with its own clock each have their own notion of time, and free-running clocks drift apart by parts per million, which becomes milliseconds within minutes. Synchronise to one master (PTP, a hardware pulse, or at least a measured offset) and check that the filter's inputs are monotonic; a message stamped in the past relative to the filter state is usually dropped silently.

Frames and gravity. By REP 145, IMU data is reported in the IMU's own body frame and the accelerometer includes gravity: an IMU at rest and level reads roughly +9.8 m/s² on its z axis, not zero. A driver that subtracts gravity, or a URDF that has the IMU frame rotated wrongly, makes the filter see a permanent acceleration and drift immediately.

Covariances that are placeholders. The message types carry covariance so the filter can weigh the source; a covariance of all zeros is defined to mean unknown, and a leading element of -1 means the field is not measured at all. Copying an identity matrix into every message tells the filter that a consumer wheel encoder and a survey-grade GPS are equally trustworthy. Set them from the datasheet noise figures or from a static test, and revisit them when the robot vibrates more than the bench did.

What to check first when fusion output lags, jumps, or drifts in one direction: the stamp source in each driver, the clock offset between devices, the IMU frame orientation against REP 145, and whether any covariance is still a default.
