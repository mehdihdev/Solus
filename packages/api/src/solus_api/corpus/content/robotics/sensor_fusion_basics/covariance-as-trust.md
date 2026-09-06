+++
title = "Fusion is weighted trust: IMU drift, complementary filters, and the Kalman idea"
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
related = [
  "corpus:robotics/sensor_fusion_basics/encoder-imu-vision-strengths-and-limits",
  "corpus:robotics/sensor_fusion_basics/timestamps-and-covariance-pitfalls",
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
  { title = "robot_localization documentation (state estimation, covariance configuration)", author = "Open Robotics", url = "https://docs.ros.org/" },
  { title = "REP 145: Conventions for IMU Sensor Drivers", author = "Open Robotics", identifier = "REP 145", url = "https://www.ros.org/reps/rep-0145.html" },
  { title = "BMI088 / BMI270 inertial measurement unit datasheets (bias and noise specifications)", author = "Bosch Sensortec", url = "https://www.bosch-sensortec.com/" },
]
+++

An IMU gives you angular rate from gyroscopes and specific force from accelerometers, at hundreds or thousands of samples per second, with almost no latency. What it does not give you is position or orientation; those are integrals, and integration turns a small constant error into a growing one. A gyroscope with a tiny bias, integrated, yields a heading error that grows linearly with time. An accelerometer bias, integrated twice for position, yields an error that grows with the square of time. This is drift, and no amount of averaging within the IMU removes it because the error is a bias, not noise.

Fusion fixes this by pairing a sensor that is good over short times with one that is good over long times. The accelerometer, at rest or in gentle motion, mostly measures gravity, so it gives an absolute reference for tilt that does not drift but is noisy and corrupted by any acceleration. The gyroscope gives smooth, fast tilt changes that drift. A complementary filter is the simplest way to combine them: trust the gyro for fast changes (high-pass) and the accelerometer for the slow average (low-pass), with a single time constant that decides where the trust hands over. It cannot do heading without a magnetometer or other absolute reference, because gravity says nothing about yaw.

A Kalman filter is the same idea made principled and multivariable. It keeps an estimate of the state and a covariance, which is a statement of how uncertain it is in each direction and how those uncertainties are correlated. Prediction (integrating the IMU) grows the covariance; a measurement (an encoder, a GPS fix, a visual pose) shrinks it. The gain that decides how far to move the estimate toward each new measurement is computed from the ratio of trust: a measurement with a small covariance pulls hard, a measurement with a large covariance barely moves the estimate. That is all a covariance is in practice: a numerical statement of how much you trust a number, and the filter is only as good as the honesty of those statements.

For an engineer arriving from electronics, the closest analogy is a phase-locked loop: a fast local oscillator (the IMU) disciplined by a slower, more accurate reference (the absolute sensor), with a loop bandwidth (the covariance ratio) that trades responsiveness against noise.
