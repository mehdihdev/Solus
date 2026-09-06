+++
title = "Camera intrinsics, shutter type, and what depth sensors cannot see"
kind = "principle"
audience = "fundamentals"
applicability = []
derivation = "solus_original"
confidence = 0.85
confidence_basis = "consensus"
drafting = "llm_assisted"
reviewer = "mhussain"
reviewed_at = 2026-09-06
status = "active"
related = [
  "corpus:robotics/sensor_fusion_basics/encoder-imu-vision-strengths-and-limits",
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
  { title = "OpenCV documentation, camera calibration and 3D reconstruction module", author = "OpenCV team", url = "https://docs.opencv.org/" },
  { title = "sensor_msgs/CameraInfo message definition and image_pipeline camera_calibration documentation", author = "Open Robotics", url = "https://docs.ros.org/" },
  { title = "REP 104: CameraInfo updates", author = "Open Robotics", identifier = "REP 104", url = "https://www.ros.org/reps/rep-0104.html" },
]
+++

A camera turns a direction in space into a pixel. The intrinsic parameters describe that mapping for one camera at one focus and zoom: a focal length in pixels for each axis, the pixel where the optical axis lands (the principal point), and a handful of distortion coefficients that describe how the lens bends straight lines toward the edges. Calibration recovers them by photographing a known pattern from many angles; without it, every measurement of size, distance, or angle derived from pixels is wrong by an unknown amount, and the error grows toward the image corners. Intrinsics change if the lens is refocused, the sensor is swapped, or the housing flexes, so a calibration is a property of an assembled unit, not of a part number. In ROS they travel alongside every image in the CameraInfo message so downstream nodes can undistort and project consistently.

Shutter type matters as soon as anything moves. A rolling shutter exposes the image one row at a time, so a scene that moves during the readout is smeared into a skew: vertical edges lean, and a fast pan makes a rigid object look sheared. A global shutter exposes every pixel at the same instant. For a stationary camera watching a slow scene the difference is invisible; for a camera on a moving robot, for visual odometry, or for anything fused with an IMU, rolling shutter introduces geometry errors that no calibration removes, and global shutter is the usual requirement.

Depth sensors each have a blind spot. Stereo cameras need texture to match between views and fail on blank walls; active structured-light and time-of-flight cameras project their own infrared light and are washed out by sunlight, absorbed by dark matte surfaces, and confused by glass, mirrors, and shiny metal; lidar is accurate and works in sunlight but returns are sparse, and it shares the transparent-and-reflective blind spot. Lighting is therefore a design input, not an afterthought: a perception stack validated under lab lighting will behave differently under sodium lamps, flicker, or a window.
