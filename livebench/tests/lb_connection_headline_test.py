"""The local connection picker preserves definition-level tentative hints."""

from livebench.local import LocalDevice
from livebench.recognition.passive import identify_port
from solus_api.livebench.bench_router import _device_wire


def test_local_device_wire_preserves_hint_without_claiming_mcu_identity() -> None:
    identity = identify_port(device="/dev/ttyUSB0", vid=0x1A86, pid=0x7523, serial=None)
    wire = _device_wire(LocalDevice(identity=identity, by_id_path=None, ambiguous=True))
    assert wire["headline"] == "Possible Arduino connection"
    assert wire["mcu_known"] is False
    assert wire["ambiguous"] is True
