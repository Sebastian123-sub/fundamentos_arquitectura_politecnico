from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def ahora() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class PagoModel(Base):
    __tablename__ = "pagos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pedido_id: Mapped[str] = mapped_column(String(36), index=True)
    monto_cop: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    medio: Mapped[str] = mapped_column(String(32))
    estado: Mapped[str] = mapped_column(String(16), default="PENDIENTE")  # APROBADO, RECHAZADO, PENDIENTE
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

class ReembolsoModel(Base):
    __tablename__ = "reembolsos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pago_id: Mapped[str] = mapped_column(String(36), index=True)
    estado: Mapped[str] = mapped_column(String(16), default="COMPLETADO")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)