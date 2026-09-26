from pathlib import Path


def test_identity_read_never_creates_files(tmp_path: Path) -> None:
    from livebench.hardware.host_identity import read_host_identity

    assert read_host_identity(home=tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_identity_read_accepts_fixed_regular_file_and_refuses_symlink(tmp_path: Path) -> None:
    from livebench.hardware.host_identity import read_host_identity

    root = tmp_path / ".solus"
    root.mkdir()
    target = root / "companion_id"
    target.write_text("c" * 32)
    assert read_host_identity(home=tmp_path) == "c" * 32
    target.unlink()
    other = tmp_path / "other"
    other.write_text("c" * 32)
    target.symlink_to(other)
    assert read_host_identity(home=tmp_path) is None
