"""Configuración externalizada (Twelve-Factor, factor III).

Ningún valor de entorno, dirección o secreto debe estar escrito en el código
de negocio. Todo entra por variables de entorno con prefijo PISHOP_.
"""
# Tipos especiales para revisar direcciones web y ocultar valores sensibles. P10
from pydantic import HttpUrl, SecretStr
# Herramientas para definir valores que pueden ajustarse desde el entorno. P10
from pydantic_settings import BaseSettings, SettingsConfigDict

# Reune en un solo lugar las opciones con las que funciona el servicio. P10
class Settings(BaseSettings):
    # Busca variables de entorno con prefijo PISHOP_ y tambien un archivo .env. P10
    model_config = SettingsConfigDict(env_prefix="PISHOP_", env_file=".env", extra="ignore")

    # Nombre que se muestra para identificar el servicio. P10
    service_name: str = "reportes-service"
    # Puerto de red previsto para recibir solicitudes. P10
    http_port: int = 8006
    # Entorno de trabajo; "dev" indica desarrollo. P10
    app_env: str = "dev"
    # Direccion del archivo SQLite que guarda los reportes. P10
    database_url: str = "sqlite+aiosqlite:///./reportes.db"
    # Valor sensible para una contrasena; puede reemplazarse en el entorno. P10
    database_password: SecretStr = SecretStr("cambiar-en-entorno")
    # Direccion del servicio que podria entregar configuracion. P10
    config_service_url: HttpUrl = "http://localhost:8010"
    # Direccion del servicio de descubrimiento Consul. P10
    consul_url: HttpUrl = "http://localhost:8500"
    # Tiempo, en segundos, entre consultas de configuracion. P10
    config_poll_seconds: int = 15
    # Tiempo maximo de espera de solicitudes HTTP, en segundos. P10
    http_timeout_seconds: float = 2.0  # timeout explícito


# Crea y devuelve la configuracion usando los valores disponibles en el entorno. P10
def get_settings() -> Settings:
    return Settings()