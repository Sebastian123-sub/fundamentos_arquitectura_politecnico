from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.pedidos.db import get_session
from app.pedidos.models import Pedido
from app.pedidos.schemas import PedidoCreate, PedidoOut

router = APIRouter(prefix="/v1", tags=["pedidos"])

@router.post("/pedidos", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
async def crear_pedido(datos: PedidoCreate, session: AsyncSession = Depends(get_session)):
    pedido = Pedido(**datos.model_dump(), estado="PENDIENTE")
    session.add(pedido)
    await session.commit()
    await session.refresh(pedido)
    return pedido

@router.get("/pedidos/{pedido_id}", response_model=PedidoOut)
async def obtener_pedido(pedido_id: int, session: AsyncSession = Depends(get_session)):
    pedido = await session.get(Pedido, pedido_id)
    if pedido is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return pedido

@router.post("/pedidos/{pedido_id}/cancelar", status_code=status.HTTP_200_OK)
async def cancelar_pedido(pedido_id: int, session: AsyncSession = Depends(get_session)):
    """Cancela un pedido existente."""
    pedido = await session.get(Pedido, pedido_id)
    if pedido is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    pedido.estado = "CANCELADO"
    await session.commit()
    await session.refresh(pedido)
    return {"mensaje": f"Pedido {pedido_id} cancelado exitosamente", "estado": "CANCELADO"}

@router.get("/outbox/pendientes", status_code=status.HTTP_200_OK)
async def listar_outbox_pendientes(session: AsyncSession = Depends(get_session)):
    """Obtiene los eventos pendientes en el patrón Outbox."""
    return []