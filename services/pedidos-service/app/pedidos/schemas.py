from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PedidoCreate(BaseModel):
    cliente_id: int = Field(gt=0)
    total: float = Field(gt=0)


class PedidoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cliente_id: int
    total: float
    estado: str
    creado_en: datetime
