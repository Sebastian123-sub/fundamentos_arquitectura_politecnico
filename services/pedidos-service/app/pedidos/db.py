import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("PEDIDOS_DATABASE_URL", "sqlite+aiosqlite:///./pedidos.db")

# NullPool: cada petición abre su conexión; evita conflictos de event loop en tests.
engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


_tablas_listas = False


async def get_session() -> AsyncIterator[AsyncSession]:
    """Crea las tablas la primera vez y entrega una sesión por petición."""
    global _tablas_listas
    if not _tablas_listas:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _tablas_listas = True
    async with SessionLocal() as session:
        yield session
