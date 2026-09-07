+++
title = "Topics, services, actions, and why sensor data drops: choosing the pattern and the QoS"
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
related = ["corpus:software/ros_conventions/tf-tree-hygiene", "corpus:software/ros_conventions/rep-103-units-and-frames"]
corpus_version = "0.1.0"
revised_in = "0.1.0"

[provenance]
source_class = "solus_authored"
source_title = "Solus engineering corpus"
source_publisher = "Solus"
source_license = "solus-proprietary"
accessed_at = 2026-09-06
checked_against = [
  { title = "ROS 2 documentation: About Quality of Service settings", author = "Open Robotics / ROS 2", identifier = "ROS 2 docs, Concepts", url = "https://docs.ros.org/" },
  { title = "ROS 2 documentation: Understanding topics, services, and actions (Beginner CLI tools tutorials)", author = "Open Robotics / ROS 2", identifier = "ROS 2 docs, Tutorials", url = "https://docs.ros.org/" },
]
+++

Three communication patterns, and the rule for choosing between them:

- Topic: many-to-many streaming, no reply. Use for anything periodic or unsolicited: sensor data, odometry, joint states, velocity commands. If losing one message is fine because the next supersedes it, it is a topic.
- Service: one request, one reply, the caller waits. Use for short, bounded operations: query a value, reset an estimator, trigger a calibration that finishes in milliseconds. Never wrap something that takes seconds in a service; the caller blocks and cannot cancel.
- Action: a goal, periodic feedback, a result, and cancellation. Use for anything long-running with progress: navigate to a pose, execute a trajectory, home an axis.

QoS is where sensor streams silently break in ROS 2. Publisher and subscriber each declare a QoS profile, and the middleware connects them only if the profiles are compatible. The two settings that matter most are reliability (reliable: retransmit until delivered; best-effort: fire and forget) and durability (volatile, or transient-local: the publisher keeps its last messages for late joiners). Compatibility is asymmetric. A reliable subscriber receives nothing from a best-effort publisher; a best-effort subscriber accepts either. A transient-local subscriber does not connect to a volatile publisher; a volatile subscriber accepts either.

Rules of thumb:

- Sensor drivers publish with the sensor-data profile (best-effort, small keep-last history). Subscribe to them best-effort too, or you receive nothing, with no error beyond a QoS-incompatibility warning in the log.
- Static or rarely-changing data that late-starting nodes must see (`/tf_static`, a map, the robot description) is published transient-local; subscribe transient-local.
- Commands you cannot afford to lose (an e-stop, a mode change) go reliable, or better, through a service or action with an explicit acknowledgement.
- When a topic "publishes but nobody receives", run `ros2 topic info -v` on the topic and compare the publisher's and subscriber's QoS before suspecting the network.

Dropped frames on a reliable camera topic over Wi-Fi are the other common symptom: reliable delivery with a small history depth means the publisher stalls on retransmits and then discards, so you get bursts and gaps. Best-effort gives smoother, lower-latency delivery for data that is superseded every frame.
