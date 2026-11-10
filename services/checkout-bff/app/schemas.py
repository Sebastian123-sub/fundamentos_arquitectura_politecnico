"""Esquemas de validación y transferencia de datos DTO (Pydantic v2).

Define los contratos de entrada y salida para los endpoints de la API,
asegurando validaciones automáticas de tipos y respuestas de error uniformes.
"""
# Tipos de datos para anotaciones de tipo estándar en Python
from typing import Any, List, Optional
# BaseModel define clases de datos validadas por Pydantic; Field permite añadir restricciones y metadatos
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Estructura canónica de error exigida por el contrato arquitectónico de PiShop Cloud."""
    # Mensaje descriptivo y legible para el cliente o desarrollador
    detalle: str = Field(..., description="Descripción legible del error")
    # Código de negocio o validación unificado (ej. 'RECURSO_NO_ENCONTRADO', 'IDEMPOTENCY_KEY_REQUERIDA')
    codigo: str = Field(..., description="Código de error de dominio o validación")


class CheckoutRequest(BaseModel):
    """Cuerpo de la petición recibida en el endpoint POST /v1/checkout."""
    # Identificador único del cliente que realiza la compra (no puede ser cadena vacía)
    cliente_id: str = Field(..., min_length=1, description="Identificador del cliente")
    # Código SKU que identifica unívocamente el producto en el catálogo
    sku: str = Field(..., min_length=1, description="Código SKU del producto")
    # Número de unidades solicitadas, restringido a ser un entero estrictamente mayor a 0 (gt=0)
    cantidad: int = Field(..., gt=0, description="Cantidad a comprar (entero positivo > 0)")
    # Método con el que se cobrará al cliente (ej. 'tarjeta', 'nequi', 'daviplata')
    medio_pago: str = Field(..., min_length=1, description="Medio de pago (ej. tarjeta, nequi)")


class PasoResultado(BaseModel):
    """Representa el resultado individual de un paso directo o de compensación en la saga."""
    # Nombre del servicio o compensación ejecutada (ej. 'catalogo', 'inventario_liberar')
    paso: str = Field(..., description="Nombre del paso o de la compensación")
    # Estado resultante del paso: 'OK' (exitoso), 'FALLIDO' (error/rechazo) o 'COMPENSADO' (rollback semántico)
    resultado: str = Field(..., description="Resultado (OK, FALLIDO, COMPENSADO)")
    # Información diagnóstica adicional con códigos HTTP o razones de fallo
    detalle: Optional[str] = Field(None, description="Información adicional del paso")


class CheckoutResponse(BaseModel):
    """Respuesta emitida tras la orquestación del checkout."""
    # Identificador final del pedido generado, o correlation_id si falló antes de crearlo en Pedidos
    pedido_id: str = Field(..., description="ID del pedido (o ID de correlación si falló antes de crearlo)")
    # Resultado global de la transacción distribuida: 'CONFIRMADO' si todos los pasos pasaron, o 'FALLIDO'
    estado: str = Field(..., description="Estado final de la saga: CONFIRMADO o FALLIDO")
    # Lista secuencial de todos los pasos ejecutados y compensaciones aplicadas
    pasos: List[PasoResultado] = Field(default_factory=list, description="Historial de pasos ejecutados")


class VitrinaItem(BaseModel):
    """Elemento individual retornado por el agregador BFF móvil (GET /v1/vitrina)."""
    # Identificador SKU del producto
    sku: str = Field(..., description="Identificador del producto")
    # Nombre comercial para mostrar en la interfaz móvil
    nombre: str = Field(..., description="Nombre comercial del producto")
    # Precio monetario en pesos colombianos obtenido desde el servicio de catálogo
    precio_cop: float = Field(..., description="Precio unitario en pesos colombianos")
    # Cantidad física disponible neta (total - reservado) calculada desde el servicio de inventario
    stock_disponible: int = Field(..., description="Unidades físicas disponibles")
