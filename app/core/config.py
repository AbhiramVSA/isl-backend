from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    app_name: str = "ISL SOS API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./app.db"
    lstm_weights_path: str = "ml_models/170-0.83.hdf5"

    # --- auth ---------------------------------------------------------------
    # Override in production. A fixed default would let anyone who has read the
    # source mint tokens for any account.
    secret_key: str = "dev-only-insecure-key-change-me-before-deploying"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 24 * 30

    # --- NVIDIA NIM proxy ---------------------------------------------------
    # Set NVIDIA_NIM_API_KEY to move the key off the mobile clients, where it is
    # extractable from the shipped binary.
    nvidia_nim_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_default_model: str = "z-ai/glm-5.2"
    nim_timeout_seconds: float = 120.0

    # --- station directory --------------------------------------------------
    stations_file: str = "data/police_stations.json"


settings = Settings()
