import io

from gear_optimizer import desktop_backend


class ReconfigurableTextStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.configuration = None

    def reconfigure(self, **kwargs):
        self.configuration = kwargs


def test_desktop_backend_forces_utf8_standard_streams(monkeypatch):
    stdin = ReconfigurableTextStream()
    stdout = ReconfigurableTextStream()
    stderr = ReconfigurableTextStream()
    monkeypatch.setattr(desktop_backend.sys, "stdin", stdin)
    monkeypatch.setattr(desktop_backend.sys, "stdout", stdout)
    monkeypatch.setattr(desktop_backend.sys, "stderr", stderr)

    desktop_backend._configure_standard_streams()

    assert stdin.configuration == {"encoding": "utf-8", "errors": "strict"}
    assert stdout.configuration == {"encoding": "utf-8", "errors": "strict"}
    assert stderr.configuration == {"encoding": "utf-8", "errors": "strict"}
