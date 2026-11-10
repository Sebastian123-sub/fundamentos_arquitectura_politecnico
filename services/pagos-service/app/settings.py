"""Configuración externalizada (Twelve-Factor, factor III).

Ningún valor de entorno, dirección o secreto debe estar escrito en el código
de negocio. Todo entra por variables de entorno con prefijo PISHOP_.
"""
from pydantic import HttpUrl, SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PISHOP_", env_file=".env", extra="ignore")

    service_name: str = "pagos-service"
    http_port: int = 8004
    app_env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./pagos.db"
    database_password: SecretStr = SecretStr("cambiar-en-entorno")
    
    # Parámetros específicos para pagos y pasarela simulada
    pasarela_modo: str = Field(default="ok", pattern="^(ok|rechaza|lenta|falla)$")
    
    config_service_url: HttpUrl = "http://localhost:8010"
    consul_url: HttpUrl = "http://localhost:8500"
    config_poll_seconds: int = 15
    http_timeout_seconds: float = 3.0  # Timeout explícito para peticiones salientes (semana 3)

def get_settings() -> Settings:
    return Settings()