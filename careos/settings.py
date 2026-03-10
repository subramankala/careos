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

    conversation_engine: str = "deterministic"
    openclaw_base_url: str = ""
    openclaw_timeout_seconds: int = 15

    twilio_whatsapp_number: str = ""
    enable_voice_escalation: bool = False
    voice_caller_id: str = ""


settings = Settings()
