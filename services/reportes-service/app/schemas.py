"""Esquemas Pydantic para validación de datos en reportes."""
# Tipo utilizado para representar la fecha y hora de creacion. P10
from datetime import datetime

# BaseModel permite revisar y ordenar los datos recibidos y enviados. P10
# ConfigDict permite ajustar como se convierten los datos para la respuesta. P10
from pydantic import BaseModel, ConfigDict


# Campos compartidos por un reporte recibido y uno que se devuelve. P10
class ReporteBase(BaseModel):
    # El titulo debe ser texto. P10
    titulo: str
    # La descripcion puede ser texto o quedar vacia. P10
    descripcion: str | None = None
    # El estado puede indicarse o toma "generado" como valor inicial. P10
    estado: str | None = "generado"


# Forma de los datos que se aceptan al crear un reporte. P10
class ReporteCreate(ReporteBase):
    # Por ahora, crear un reporte usa los campos de ReporteBase tal cual. P10
    pass


# Forma de los datos que se devuelven despues de guardar un reporte. P10
class ReporteResponse(ReporteBase):
    # Identificador asignado por la base de datos. P10
    id: int
    # Fecha y hora en que se creo el reporte. P10
    fecha_creacion: datetime

    # Permite construir esta respuesta leyendo directamente el objeto guardado. P10
    model_config = ConfigDict(from_attributes=True)