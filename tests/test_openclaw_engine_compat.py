from careos.conversation.openclaw_engine import OpenClawConversationEngine


def test_candidate_paths_include_compat_variants() -> None:
    engine = OpenClawConversationEngine(base_url="http://127.0.0.1:9999", fallback_path="/custom/fallback")
    paths = engine._candidate_paths()
    assert paths[0] == "/custom/fallback"
    assert "/v1/careos/fallback" in paths
    assert "/api/v1/careos/fallback" in paths


def test_extract_text_supports_multiple_response_shapes() -> None:
    text, action = OpenClawConversationEngine._extract_text({"text": "hello", "action": "openclaw_fallback"})
    assert text == "hello"
    assert action == "openclaw_fallback"

    text, _ = OpenClawConversationEngine._extract_text({"response": "hi"})
    assert text == "hi"

    text, _ = OpenClawConversationEngine._extract_text({"message": "yo"})
    assert text == "yo"

    text, _ = OpenClawConversationEngine._extract_text({"choices": [{"message": {"content": "from choices"}}]})
    assert text == "from choices"
