from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Keycloak settings
    keycloak_url: str = "http://keycloak:8080"  # Internal Docker URL
    keycloak_public_url: str = "http://localhost:8080"  # Browser-accessible URL
    keycloak_realm: str = "reports-realm"
    keycloak_client_id: str = "reports-frontend"
    keycloak_client_secret: str = ""

    # Redis settings
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # Session settings
    session_cookie_name: str = "bionicpro_session"
    session_ttl: int = 3600  # 1 hour
    access_token_ttl: int = 120  # 2 minutes

    # Security settings
    token_encryption_key: str = "your-32-byte-encryption-key-here!"

    # CORS settings
    frontend_url: str = "http://localhost:3000"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
