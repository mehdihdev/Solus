+++
title = "Encoders, IMUs, and vision: what each measures well and where each fails"
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
  { title = "REP 105: Coordinate Frames for Mobile Platforms (odom vs map drift semantics)", author = "Open Robotics", identifier = "REP 105", url = "https://www.ros.org/reps/rep-0105.html" },
  { title = "robot_localization documentation, sensor configuration and fusion of odometry, IMU, and pose sources", author = "Open Robotics", url = "https://docs.ros.org/" },
  { title = "OpenCV documentation, camera calibration and 3D reconstruction", author = "OpenCV team", url = "https://docs.opencv.org/" },
]
+++

Each sensor family is good at one thing and the fusion design is mostly about knowing which. The table is a default; a specific sensor's datasheet overrides it.

| Sensor | Measures directly | Good over | Fails when | Latency and rate |
| --- | --- | --- | --- | --- |
| Encoder (incremental or absolute) | Shaft angle; velocity by differencing | Any duration, as long as the shaft is coupled to what you care about | The wheel slips, the belt stretches, backlash hides motion, or the incremental count is lost on a power cycle | Very low latency; rate limited only by counting hardware |
| IMU (gyro plus accelerometer) | Angular rate; specific force including gravity | Fractions of a second to a few seconds for orientation; much less for position | Integrated for long, or in sustained acceleration where tilt from gravity cannot be separated from motion; vibration aliases into bias | Very low latency; hundreds to thousands of samples per second |
| Camera / visual odometry | Bearing to features; pose by matching them over time | Long durations if features persist; absolute if landmarks are known | Motion blur, low light, textureless walls, repetitive patterns, fast rotation between frames; scale is ambiguous with one camera | Tens of milliseconds and up; tens of frames per second |
| Wheel odometry (encoders through a kinematic model) | Body displacement estimate | Short to medium distances on good floors | Slip, uneven ground, wrong wheel radius or track width; heading error grows fastest | Low latency; same rate as the encoders |

Defaults that follow: let the IMU provide angular rate and short-term orientation, let encoders or wheel odometry provide short-term translation, and let vision or another absolute source correct the slow drift of both. Keep the fast, drifting, continuous estimate (REP 105's odom) separate from the slow, jumping, globally correct one (map), because controllers want continuity and planners want correctness, and no single estimate gives both.

Limits of this table: an absolute encoder on a directly driven joint is close to ground truth and should be trusted almost completely; an IMU on a vibrating chassis without mechanical isolation is far worse than the table suggests; and a camera with a good IMU (visual-inertial odometry) is a different, much stronger sensor than a camera alone.
