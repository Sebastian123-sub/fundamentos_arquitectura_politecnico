"""Configuración externalizada (Twelve-Factor, factor III).

Toda la configuración entra por variables PISHOP_* con pydantic-settings.
Solo settings.py contiene valores por defecto para desarrollo local.
"""
from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PISHOP_",
        env_file=".env",
        extra="ignore",
    )

    # Identidad y servidor
    service_name: str = "checkout-bff"
    http_port: int = 8080
    app_env: str = "dev"

    # Persistencia local (Factor IV)
    database_url: str = "sqlite+aiosqlite:///./local.db"
    database_password: SecretStr = SecretStr("cambiar-en-entorno")

    # Servicios de soporte (Semanas 2 y 4)
    config_service_url: HttpUrl = HttpUrl("http://localhost:8010")
    consul_url: HttpUrl = HttpUrl("http://localhost:8500")
    config_poll_seconds: int = 15

    # Servicios downstream con URLs y timeouts explícitos individuales (Semana 3)
    catalogo_url: HttpUrl = HttpUrl("http://localhost:8001")
    timeout_catalogo_seconds: float = 2.0

    inventario_url: HttpUrl = HttpUrl("http://localhost:8002")
    timeout_inventario_seconds: float = 2.0

    pedidos_url: HttpUrl = HttpUrl("http://localhost:8003")
    timeout_pedidos_seconds: float = 2.0

    pagos_url: HttpUrl = HttpUrl("http://localhost:8004")
    timeout_pagos_seconds: float = 2.0

    # Timeout general de contingencia
    http_timeout_seconds: float = 2.0


def get_settings() -> Settings:
    return Settings()
