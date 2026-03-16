from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAREOS_", env_file=".env", extra="ignore")

    database_url: str = ""
    use_in_memory: bool = False

    twilio_auth_token: str = ""
    twilio_account_sid: str = ""
    validate_twilio_signature: bool = True
    public_webhook_base_url: str = ""

    log_level: str = "INFO"
    default_timezone: str = "UTC"

    api_host: str = "0.0.0.0"
    api_port: int = 8115
    api_workers: int = 1

    scheduler_poll_seconds: int = 30
    scheduler_patient_ids: str = ""
    enable_scheduler_whatsapp_push: bool = False
    enable_scheduler_status_alerts: bool = True
    scheduler_low_adherence_threshold: float = 50.0
    scheduler_critical_missed_grace_minutes: int = 30
    scheduler_daily_summary_hour_local: int = 20

    conversation_engine: str = "deterministic"
    openclaw_base_url: str = ""
    openclaw_fallback_path: str = "/v1/careos/fallback"
    openclaw_responses_path: str = "/v1/responses"
    openclaw_gateway_token: str = ""
    openclaw_timeout_seconds: int = 15
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: int = 15
    gateway_mode: str = "disabled"
    gateway_careos_base_url: str = "http://127.0.0.1:8115"
    gateway_dashboard_base_url: str = "http://127.0.0.1:8000"
    gateway_intent_min_confidence: float = 0.72
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8220
    gateway_openclaw_base_url: str = ""
    gateway_openclaw_fallback_path: str = ""
    gateway_openclaw_responses_path: str = ""
    gateway_openclaw_token: str = ""
    gateway_pending_action_ttl_minutes: int = 10
    gateway_conversation_mode: str = "openclaw_first"

    twilio_whatsapp_number: str = ""
    enable_voice_escalation: bool = False
    voice_caller_id: str = ""
    onboarding_session_ttl_hours: int = 24
    onboarding_verification_ttl_hours: int = 48


settings = Settings()
