"""Orquestador de Saga y Compensaciones para Checkout BFF (P06).

Patrón Saga por Orquestación: el BFF coordina secuencialmente
Catálogo -> Inventario -> Pedidos -> Pagos. Si un paso falla,
dispara las compensaciones en orden inverso.
"""
import uuid
from typing import Dict, List, Optional, Tuple
import httpx

from app.schemas import CheckoutRequest, CheckoutResponse, PasoResultado
from app.settings import Settings


def generar_id_correlacion() -> str:
    """Genera un ID de correlación único para asociar la reserva previa a la creación del pedido.
    
    Decisión de diseño: el contrato de inventario exige `pedido_id`, pero el pedido aún no
    ha sido creado. Usamos un ID de correlación temporal que luego se enlaza al pedido.
    """
    return f"corr-{uuid.uuid4().hex[:12]}"


async def orquestar_checkout(
    payload: CheckoutRequest,
    idempotency_key: str,
    client: httpx.AsyncClient,
    settings: Settings,
) -> CheckoutResponse:
    """Ejecuta la saga de checkout y sus compensaciones en orden inverso ante fallos."""
    correlation_id = generar_id_correlacion()
    pedido_id = correlation_id
    reserva_id: Optional[str] = None
    pago_id: Optional[str] = None
    pago_requiere_reembolso = False
    pasos: List[PasoResultado] = []
    saga_exitosa = True

    # -------------------------------------------------------------
    # PASO 1: Catálogo (Validar producto y precio)
    # -------------------------------------------------------------
    monto_cop: float = 0.0
    try:
        url_cat = f"{str(settings.catalogo_url).rstrip('/')}/v1/productos/{payload.sku}"
        resp_cat = await client.get(url_cat, timeout=settings.timeout_catalogo_seconds)
        if resp_cat.status_code == 200:
            data_cat = resp_cat.json()
            if data_cat.get("publicado") is True:
                precio_cop = float(data_cat.get("precio_cop", 0))
                monto_cop = precio_cop * payload.cantidad
                pasos.append(PasoResultado(
                    paso="catalogo",
                    resultado="OK",
                    detalle=f"Producto {payload.sku} verificado y publicado (precio: {precio_cop})"
                ))
            else:
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="catalogo",
                    resultado="FALLIDO",
                    detalle=f"Producto {payload.sku} no se encuentra publicado"
                ))
        else:
            saga_exitosa = False
            pasos.append(PasoResultado(
                paso="catalogo",
                resultado="FALLIDO",
                detalle=f"Catálogo respondió HTTP {resp_cat.status_code}"
            ))
    except Exception as exc:
        saga_exitosa = False
        pasos.append(PasoResultado(
            paso="catalogo",
            resultado="FALLIDO",
            detalle=f"Error o timeout en catálogo: {exc.__class__.__name__}"
        ))

    # -------------------------------------------------------------
    # PASO 2: Inventario (Reservar stock)
    # -------------------------------------------------------------
    if saga_exitosa:
        try:
            url_inv = f"{str(settings.inventario_url).rstrip('/')}/v1/reservas"
            body_inv = {
                "sku": payload.sku,
                "cantidad": payload.cantidad,
                "pedido_id": correlation_id,
            }
            headers_inv = {"Idempotency-Key": f"{idempotency_key}-reserva"}
            resp_inv = await client.post(
                url_inv,
                json=body_inv,
                headers=headers_inv,
                timeout=settings.timeout_inventario_seconds,
            )
            if resp_inv.status_code in (200, 201):
                data_inv = resp_inv.json()
                reserva_id = str(data_inv.get("reserva_id", f"res-{uuid.uuid4().hex[:6]}"))
                pasos.append(PasoResultado(
                    paso="inventario",
                    resultado="OK",
                    detalle=f"Reserva {reserva_id} confirmada"
                ))
            elif resp_inv.status_code == 409:
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="inventario",
                    resultado="FALLIDO",
                    detalle="Stock insuficiente (HTTP 409)"
                ))
            else:
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="inventario",
                    resultado="FALLIDO",
                    detalle=f"Inventario respondió HTTP {resp_inv.status_code}"
                ))
        except Exception as exc:
            saga_exitosa = False
            pasos.append(PasoResultado(
                paso="inventario",
                resultado="FALLIDO",
                detalle=f"Error o timeout en inventario: {exc.__class__.__name__}"
            ))

    # -------------------------------------------------------------
    # PASO 3: Pedidos (Crear pedido)
    # -------------------------------------------------------------
    if saga_exitosa:
        try:
            url_ped = f"{str(settings.pedidos_url).rstrip('/')}/v1/pedidos"
            body_ped = {
                "cliente_id": payload.cliente_id,
                "sku": payload.sku,
                "cantidad": payload.cantidad,
                "monto_cop": monto_cop,
            }
            resp_ped = await client.post(
                url_ped,
                json=body_ped,
                timeout=settings.timeout_pedidos_seconds,
            )
            if resp_ped.status_code in (200, 201):
                data_ped = resp_ped.json()
                pedido_id = str(data_ped.get("pedido_id", correlation_id))
                pasos.append(PasoResultado(
                    paso="pedidos",
                    resultado="OK",
                    detalle=f"Pedido {pedido_id} creado en estado {data_ped.get('estado', 'CREADO')}"
                ))
            else:
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="pedidos",
                    resultado="FALLIDO",
                    detalle=f"Pedidos respondió HTTP {resp_ped.status_code}"
                ))
        except Exception as exc:
            saga_exitosa = False
            pasos.append(PasoResultado(
                paso="pedidos",
                resultado="FALLIDO",
                detalle=f"Error o timeout en pedidos: {exc.__class__.__name__}"
            ))

    # -------------------------------------------------------------
    # PASO 4: Pagos (Cobrar)
    # -------------------------------------------------------------
    if saga_exitosa:
        try:
            url_pag = f"{str(settings.pagos_url).rstrip('/')}/v1/pagos"
            body_pag = {
                "pedido_id": pedido_id,
                "monto_cop": monto_cop,
                "medio": payload.medio_pago,
            }
            headers_pag = {"Idempotency-Key": f"{idempotency_key}-pago"}
            resp_pag = await client.post(
                url_pag,
                json=body_pag,
                headers=headers_pag,
                timeout=settings.timeout_pagos_seconds,
            )
            if resp_pag.status_code in (200, 201):
                data_pag = resp_pag.json()
                pago_id = str(data_pag.get("pago_id", f"pag-{uuid.uuid4().hex[:6]}"))
                estado_pago = str(data_pag.get("estado", "")).upper()
                if estado_pago == "APROBADO":
                    pago_requiere_reembolso = True
                    pasos.append(PasoResultado(
                        paso="pagos",
                        resultado="OK",
                        detalle=f"Pago {pago_id} APROBADO"
                    ))
                elif estado_pago == "PENDIENTE":
                    saga_exitosa = False
                    pago_requiere_reembolso = True
                    pasos.append(PasoResultado(
                        paso="pagos",
                        resultado="FALLIDO",
                        detalle=f"Pago {pago_id} en estado PENDIENTE (se trata como fallo y requiere reembolso/cancelación)"
                    ))
                else:
                    saga_exitosa = False
                    pago_requiere_reembolso = False
                    pasos.append(PasoResultado(
                        paso="pagos",
                        resultado="FALLIDO",
                        detalle=f"Pago {pago_id} RECHAZADO (no cobrado, no requiere reembolso)"
                    ))
            else:
                saga_exitosa = False
                pago_requiere_reembolso = False
                pasos.append(PasoResultado(
                    paso="pagos",
                    resultado="FALLIDO",
                    detalle=f"Pagos respondió HTTP {resp_pag.status_code}"
                ))
        except Exception as exc:
            saga_exitosa = False
            pago_requiere_reembolso = False
            pasos.append(PasoResultado(
                paso="pagos",
                resultado="FALLIDO",
                detalle=f"Error o timeout en pagos: {exc.__class__.__name__}"
            ))

    # -------------------------------------------------------------
    # COMPENSACIONES (en orden inverso ante cualquier fallo)
    # -------------------------------------------------------------
    if not saga_exitosa:
        # Compensación 4 -> Reembolsar si se cobró o quedó pendiente
        if pago_id and pago_requiere_reembolso:
            try:
                url_reemb = f"{str(settings.pagos_url).rstrip('/')}/v1/pagos/{pago_id}/reembolso"
                headers_reemb = {"Idempotency-Key": f"{idempotency_key}-reembolso"}
                resp_reemb = await client.post(
                    url_reemb,
                    headers=headers_reemb,
                    timeout=settings.timeout_pagos_seconds,
                )
                pasos.append(PasoResultado(
                    paso="pagos_reembolso",
                    resultado="COMPENSADO" if resp_reemb.status_code in (200, 201) else "FALLIDO",
                    detalle=f"Reembolso de pago {pago_id} ejecutado (HTTP {resp_reemb.status_code})"
                ))
            except Exception as exc:
                pasos.append(PasoResultado(
                    paso="pagos_reembolso",
                    resultado="FALLIDO",
                    detalle=f"Error al reembolsar {pago_id}: {exc.__class__.__name__}"
                ))

        # Compensación 3 -> Cancelar pedido si fue creado
        if pedido_id and pedido_id != correlation_id:
            try:
                url_canc = f"{str(settings.pedidos_url).rstrip('/')}/v1/pedidos/{pedido_id}/cancelar"
                resp_canc = await client.post(
                    url_canc,
                    timeout=settings.timeout_pedidos_seconds,
                )
                pasos.append(PasoResultado(
                    paso="pedidos_cancelar",
                    resultado="COMPENSADO" if resp_canc.status_code in (200, 201) else "FALLIDO",
                    detalle=f"Cancelación de pedido {pedido_id} ejecutada (HTTP {resp_canc.status_code})"
                ))
            except Exception as exc:
                pasos.append(PasoResultado(
                    paso="pedidos_cancelar",
                    resultado="FALLIDO",
                    detalle=f"Error al cancelar pedido {pedido_id}: {exc.__class__.__name__}"
                ))

        # Compensación 2 -> Liberar reserva de inventario si se reservó
        if reserva_id:
            try:
                url_lib = f"{str(settings.inventario_url).rstrip('/')}/v1/reservas/{reserva_id}/liberar"
                headers_lib = {"Idempotency-Key": f"{idempotency_key}-liberar"}
                resp_lib = await client.post(
                    url_lib,
                    headers=headers_lib,
                    timeout=settings.timeout_inventario_seconds,
                )
                pasos.append(PasoResultado(
                    paso="inventario_liberar",
                    resultado="COMPENSADO" if resp_lib.status_code in (200, 201) else "FALLIDO",
                    detalle=f"Liberación de reserva {reserva_id} ejecutada (HTTP {resp_lib.status_code})"
                ))
            except Exception as exc:
                pasos.append(PasoResultado(
                    paso="inventario_liberar",
                    resultado="FALLIDO",
                    detalle=f"Error al liberar reserva {reserva_id}: {exc.__class__.__name__}"
                ))

    estado_final = "CONFIRMADO" if saga_exitosa else "FALLIDO"
    return CheckoutResponse(
        pedido_id=pedido_id,
        estado=estado_final,
        pasos=pasos,
    )
