"""Modelo de datos para el servicio de reportes."""
# Se usan para guardar automaticamente la fecha y hora de creacion. P10
from datetime import datetime, timezone

# Tipos de columna usados por la tabla: numero, texto corto, texto largo y fecha. P10
from sqlalchemy import Column, DateTime, Integer, String, Text

# Clase base que registra este modelo como una tabla de la base de datos. P10
from app.database import Base


# Esta clase describe como se guarda cada reporte en SQLite. P10
class ReporteModel(Base):
    # Nombre de la tabla que se creara en la base de datos. P10
    __tablename__ = "reportes"

    # Identificador unico que la base de datos asigna a cada reporte. P10
    id = Column(Integer, primary_key=True, index=True)
    # Titulo obligatorio, con un maximo de 150 caracteres. P10
    titulo = Column(String(150), nullable=False)
    # Descripcion larga opcional. P10
    descripcion = Column(Text, nullable=True)
    # Estado del reporte; si no se indica otro, sera "generado". P10
    estado = Column(String(50), default="generado")
    # Fecha de creacion; se completa automaticamente con la hora actual. P10
    fecha_creacion = Column(
        # Indica que se guarda una fecha con informacion de zona horaria. P10
        DateTime(timezone=True),
        # Usa la hora actual en UTC como valor inicial. P10
        default=lambda: datetime.now(timezone.utc),
    )