"""Configuración externalizada (Twelve-Factor App, Factor III: Configuración).

Toda la configuración del microservicio entra por variables de entorno con prefijo PISHOP_
utilizando pydantic-settings. settings.py contiene únicamente los valores por defecto
para desarrollo local y pruebas unitarias aisladas.
"""
# Importa tipos especializados de Pydantic: HttpUrl para validar URLs y SecretStr para enmascarar secretos
from pydantic import HttpUrl, SecretStr
# Importa la clase base de configuraciones y el diccionario de configuración de Pydantic Settings
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Clase principal que mapea y valida las variables de entorno del sistema."""

    # Configuración de carga del modelo:
    # env_prefix: mapea automáticamente variables del sistema que comiencen por 'PISHOP_' (ej. PISHOP_HTTP_PORT)
    # env_file: archivo local alternativo para cargar variables si existe (.env)
    # extra: ignora variables de entorno adicionales que pertenezcan a otros servicios
    model_config = SettingsConfigDict(
        env_prefix="PISHOP_",
        env_file=".env",
        extra="ignore",
    )

    # Identidad del microservicio y puerto asignado en la matriz de arquitectura
    service_name: str = "checkout-bff"     # Nombre representativo del microservicio compuesto
    http_port: int = 8080                 # Puerto TCP estándar fijado en el contrato (8080)
    app_env: str = "dev"                  # Entorno de despliegue actual: 'dev', 'qa', 'stg' o 'prod'

    # Persistencia local (Twelve-Factor, Factor IV: Backing Services)
    database_url: str = "sqlite+aiosqlite:///./local.db"             # Cadena de conexión asíncrona a la base de datos
    database_password: SecretStr = SecretStr("cambiar-en-entorno")    # Secreto protegido para evitar fugas en logs o impresiones

    # Servicios de soporte de infraestructura (Semanas 2 y 4)
    config_service_url: HttpUrl = HttpUrl("http://localhost:8010")  # URL del servidor centralizado de configuración
    consul_url: HttpUrl = HttpUrl("http://localhost:8500")          # URL de Consul para descubrimiento de servicios (Service Discovery)
    config_poll_seconds: int = 15                                   # Intervalo en segundos para refrescar configuraciones dinámicas

    # Servicios downstream con URLs base y timeouts explícitos individuales (Semana 3: Resiliencia y Fail-Fast)
    catalogo_url: HttpUrl = HttpUrl("http://localhost:8001")        # URL base del microservicio de Catálogo (P01)
    timeout_catalogo_seconds: float = 2.0                          # Tiempo máximo de espera para llamadas a catálogo antes de abortar

    inventario_url: HttpUrl = HttpUrl("http://localhost:8002")      # URL base del microservicio de Inventario (P02)
    timeout_inventario_seconds: float = 2.0                        # Timeout estricto para operaciones de reserva y consulta de stock

    pedidos_url: HttpUrl = HttpUrl("http://localhost:8003")         # URL base del microservicio de Pedidos (P03)
    timeout_pedidos_seconds: float = 2.0                           # Timeout máximo para creación y cancelación de pedidos

    pagos_url: HttpUrl = HttpUrl("http://localhost:8004")           # URL base del microservicio de Pagos (P04)
    timeout_pagos_seconds: float = 2.0                             # Timeout para procesamiento de cobros y reembolsos

    # Timeout general de contingencia para el cliente HTTP asíncrono
    http_timeout_seconds: float = 2.0


def get_settings() -> Settings:
    """Función fábrica que crea y retorna la instancia de configuración actual."""
    return Settings()
