from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ISL Recognition API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./app.db"
    lstm_weights_path: str = "ml_models/170-0.83.hdf5"
    # Comma-separated list of allowed browser origins; "*" = any.
    cors_origins: str = "*"


settings = Settings()
