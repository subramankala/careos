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
