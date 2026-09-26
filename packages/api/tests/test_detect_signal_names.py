from solus_api.hardware.detect import accepted_part_name


def test_default_names_use_robot_and_stable_bus_address() -> None:
    assert accepted_part_name("Follower", "3", "actuators", None, None, None) == "Follower-Motor-3"
    assert (
        accepted_part_name("Follower", "17", "actuators", None, None, None) == "Follower-Motor-17"
    )
    assert accepted_part_name("Follower", "A0", "sensors", None, None, None) == "address A0"


def test_reviewed_and_repo_names_take_precedence() -> None:
    assert accepted_part_name("R", "3", "actuators", "Wrist", "Elbow", "Shoulder") == "Wrist"
    assert accepted_part_name("R", "3", "actuators", None, "Elbow", "Shoulder") == "Elbow"
    assert accepted_part_name("R", "3", "actuators", None, None, "Shoulder") == "Shoulder"
