"""Esquemas de validación y transferencia de datos (Pydantic v2)."""
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detalle: str = Field(..., description="Descripción legible del error")
    codigo: str = Field(..., description="Código de error de dominio o validación")


class CheckoutRequest(BaseModel):
    cliente_id: str = Field(..., min_length=1, description="Identificador del cliente")
    sku: str = Field(..., min_length=1, description="Código SKU del producto")
    cantidad: int = Field(..., gt=0, description="Cantidad a comprar (entero positivo > 0)")
    medio_pago: str = Field(..., min_length=1, description="Medio de pago (ej. tarjeta, nequi)")


class PasoResultado(BaseModel):
    paso: str = Field(..., description="Nombre del paso o de la compensación")
    resultado: str = Field(..., description="Resultado (OK, FALLIDO, COMPENSADO)")
    detalle: Optional[str] = Field(None, description="Información adicional del paso")


class CheckoutResponse(BaseModel):
    pedido_id: str = Field(..., description="ID del pedido (o ID de correlación si falló antes de crearlo)")
    estado: str = Field(..., description="Estado final de la saga: CONFIRMADO o FALLIDO")
    pasos: List[PasoResultado] = Field(default_factory=list, description="Historial de pasos ejecutados")


class VitrinaItem(BaseModel):
    sku: str = Field(..., description="Identificador del producto")
    nombre: str = Field(..., description="Nombre comercial del producto")
    precio_cop: float = Field(..., description="Precio unitario en pesos colombianos")
    stock_disponible: int = Field(..., description="Unidades físicas disponibles")
