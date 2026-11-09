"""Configuración de la base de datos asíncrona con SQLAlchemy y aiosqlite."""
# Tipo que describe los valores que la funcion de sesion va entregando. P10
from collections.abc import AsyncIterator

# Herramientas para abrir conexiones y sesiones de base de datos asincronas. P10
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
# Clase base que se usa para declarar las tablas como clases de Python. P10
from sqlalchemy.orm import DeclarativeBase

# Permite obtener la direccion de la base de datos y otras opciones. P10
from app.settings import get_settings

# Carga la configuracion del proyecto. P10
settings = get_settings()

# Prepara la conexion usando la direccion configurada. P10
engine = create_async_engine(
    settings.database_url,
    # Muestra instrucciones de la base de datos solo durante el desarrollo. P10
    echo=settings.app_env == "dev",
)

# Define como se abriran las sesiones que usan las rutas. P10
AsyncSessionLocal = async_sessionmaker(
    # Todas las sesiones usaran la conexion preparada arriba. P10
    bind=engine,
    # Cada sesion sera asincrona. P10
    class_=AsyncSession,
    # Permite seguir leyendo los objetos despues de guardar cambios. P10
    expire_on_commit=False,
)


# Clase comun de la que heredan los modelos que representan tablas. P10
class Base(DeclarativeBase):
    # No necesita contenido adicional; SQLAlchemy aporta el funcionamiento. P10
    pass


# Abre una sesion para una solicitud y la entrega a quien la necesite. P10
async def get_db() -> AsyncIterator[AsyncSession]:
    # Abre la sesion y se asegura de cerrarla al terminar su uso. P10
    async with AsyncSessionLocal() as session:
        # Entrega la sesion a la ruta que la solicito. P10
        yield session