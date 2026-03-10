from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_env_example_contains_required_keys() -> None:
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    required = [
        "CAREOS_DATABASE_URL=",
        "CAREOS_USE_IN_MEMORY=",
        "CAREOS_VALIDATE_TWILIO_SIGNATURE=",
        "CAREOS_TWILIO_AUTH_TOKEN=",
        "CAREOS_PUBLIC_WEBHOOK_BASE_URL=",
        "CAREOS_SCHEDULER_POLL_SECONDS=",
        "CAREOS_DEFAULT_TIMEZONE=",
        "CAREOS_CONVERSATION_ENGINE=",
        "CAREOS_LOG_LEVEL=",
    ]
    for key in required:
        assert key in content


def test_systemd_helper_is_dry_run_first() -> None:
    script = (REPO_ROOT / "scripts" / "install_systemd_units.sh").read_text(encoding="utf-8")
    assert "--apply" in script
    assert "Dry run" in script
    assert "systemctl daemon-reload" in script
