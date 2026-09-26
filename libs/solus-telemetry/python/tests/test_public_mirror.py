def test_public_mirror_requires_explicit_configuration():
    import pytest
    import solus_telemetry as solus
    assert callable(solus.mirror)
    with pytest.raises(TypeError):
        solus.mirror(object())
