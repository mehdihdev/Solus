from solus_api.hardware.detect import accepted_part_name


def test_default_names_use_robot_and_stable_bus_address() -> None:
    assert accepted_part_name("Follower", "3", None, None, None, streamed=False) == (
        "Follower-Motor-3"
    )
    assert accepted_part_name("Follower", "17", None, None, None, streamed=False) == (
        "Follower-Motor-17"
    )
    # A line stream's rows are its readings (SOLUSDEV-326: no body says so any more).
    assert accepted_part_name("Follower", "A0", None, None, None, streamed=True) == "address A0"


def test_reviewed_and_repo_names_take_precedence() -> None:
    assert accepted_part_name("R", "3", "Wrist", "Elbow", "Shoulder", streamed=False) == "Wrist"
    assert accepted_part_name("R", "3", None, "Elbow", "Shoulder", streamed=True) == "Elbow"
    assert accepted_part_name("R", "3", None, None, "Shoulder", streamed=False) == "Shoulder"
