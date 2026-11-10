from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field

class PagoCrear(BaseModel):
    pedido_id: str = Field(min_length=1)
    monto_cop: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    medio: str = Field(min_length=2, max_length=32)

class PagoLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    pedido_id: str
    monto_cop: Decimal
    medio: str
    estado: str  # APROBADO, RECHAZADO, PENDIENTE
    creado_en: datetime

class ReembolsoLeer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    pago_id: str
    estado: str
    creado_en: datetime