from careos.gateway.careos_adapter import CareOSAdapter


def test_resolve_context_url_encodes_plus_sign(monkeypatch) -> None:
    adapter = CareOSAdapter(base_url="http://127.0.0.1:8115")
    captured: dict[str, str] = {}

    def _fake_request(path: str, *, method: str = "GET", payload=None):  # type: ignore[no-untyped-def]
        captured["path"] = path
        return {"ok": True}

    monkeypatch.setattr(adapter, "_request", _fake_request)
    adapter.resolve_context("whatsapp:+14085157095")

    assert captured["path"] == "/internal/resolve-context?phone_number=whatsapp%3A%2B14085157095"


def test_generate_dashboard_view_posts_to_careos_dash(monkeypatch) -> None:
    adapter = CareOSAdapter(base_url="http://127.0.0.1:8115")
    adapter.dashboard_base_url = "http://127.0.0.1:8000"
    captured: dict[str, object] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"url":"http://dash.local/v/token","expires_in_seconds":1800}'

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = request.data.decode("utf-8")
        return _Response()

    monkeypatch.setattr("careos.gateway.careos_adapter.urlopen", _fake_urlopen)
    result = adapter.generate_dashboard_view(
        tenant_id="tenant-1",
        patient_id="patient-1",
        actor_id="actor-1",
    )

    assert captured["url"] == "http://127.0.0.1:8000/generate-view"
    assert captured["method"] == "POST"
    assert '"patient_id": "patient-1"' in str(captured["body"])
    assert result["url"] == "http://dash.local/v/token"
