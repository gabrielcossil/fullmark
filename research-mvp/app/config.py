from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./fullmark.db"
    environment: str = "development"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    storage_proxy_url: str = ""
    storage_proxy_token: str = ""
    internal_token: str = ""
    browser_use_api_key: str = ""
    browser_network_policy_id: str = ""
    browser_model: str = "gpt-6-luna"
    browser_max_cost_usd: float = 25
    ncbi_email: str = ""
    ncbi_api_key: str = ""
    local_storage: str = "./data"
    demo_mode: bool = False


@lru_cache
def settings():
    s = Settings()
    if s.environment == "production":
        if s.demo_mode or not s.database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Production requires PostgreSQL and demo_mode=false")
        if not all(
            (
                s.supabase_url,
                s.supabase_publishable_key,
                (s.supabase_secret_key or (s.storage_proxy_url and len(s.storage_proxy_token) >= 32)),
                len(s.internal_token) >= 32,
            )
        ):
            raise RuntimeError("Production credentials are incomplete")
    return s
