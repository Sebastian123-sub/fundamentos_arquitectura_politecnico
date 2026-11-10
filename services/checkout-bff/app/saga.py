"""Orquestador de Saga y Compensaciones para Checkout BFF (P06).

Implementa el patrón Saga por Orquestación: el BFF actúa como coordinador central
que ejecuta una secuencia distribuida de pasos:
    Catálogo -> Inventario -> Pedidos -> Pagos.
Si cualquier paso falla o agota el tiempo de espera (timeout), se suspende la ejecución
hacia adelante y se activan transacciones de compensación en orden estrictamente inverso:
    Reembolsar Pago -> Cancelar Pedido -> Liberar Reserva de Inventario.
"""
# Módulo para generar identificadores universales únicos (UUID)
import uuid
# Tipos para anotaciones estáticas en Python
from typing import Dict, List, Optional, Tuple
# Cliente HTTP asíncrono para comunicarse sin bloquear el bucle de eventos
import httpx

# Importa los esquemas de petición, respuesta y resultado de pasos
from app.schemas import CheckoutRequest, CheckoutResponse, PasoResultado
# Importa la clase de configuración de entornos y timeouts
from app.settings import Settings


def generar_id_correlacion() -> str:
    """Genera un identificador de correlación único para vincular pasos previos al pedido formal.
    
    Decisión de diseño arquitectónico:
    El contrato de inventario exige un 'pedido_id' para formalizar la reserva, pero en el flujo
    hacia adelante el pedido aún no ha sido creado en el servicio de Pedidos.
    Se utiliza este correlation_id temporal que posteriormente se asocia al crear el pedido.
    """
    # Retorna un prefijo identificable junto a 12 caracteres hexadecimales aleatorios
    return f"corr-{uuid.uuid4().hex[:12]}"


async def orquestar_checkout(
    payload: CheckoutRequest,
    idempotency_key: str,
    client: httpx.AsyncClient,
    settings: Settings,
) -> CheckoutResponse:
    """Ejecuta la saga de compra y coordina las compensaciones semánticas ante fallos.
    
    Argumentos:
        payload: Datos de compra (cliente_id, sku, cantidad, medio_pago).
        idempotency_key: Clave de idempotencia enviada por el cliente.
        client: Instancia AsyncClient compartida para optimizar conexiones HTTP.
        settings: Objeto con URLs y timeouts configurados.
        
    Retorna:
        CheckoutResponse con el estado final (CONFIRMADO o FALLIDO) y la bitácora de pasos.
    """
    # 1. Generar correlation ID inicial para rastrear la saga
    correlation_id = generar_id_correlacion()
    # Inicialmente el pedido_id toma el valor de correlación hasta que Pedidos asigne el definitivo
    pedido_id = correlation_id
    # Variable para almacenar el ID de reserva de inventario si se concreta exitosamente
    reserva_id: Optional[str] = None
    # Variable para almacenar el ID de pago si se procesa en la pasarela
    pago_id: Optional[str] = None
    # Bandera que indica si el dinero fue debitado o retenido y amerita reembolso
    pago_requiere_reembolso = False
    # Historial detallado de auditoría de cada paso ejecutado
    pasos: List[PasoResultado] = []
    # Bandera principal que determina si el flujo hacia adelante continúa o aborta
    saga_exitosa = True

    # -------------------------------------------------------------
    # PASO 1: Catálogo (Validar que el producto exista y esté publicado)
    # -------------------------------------------------------------
    monto_cop: int = 0
    try:
        # Construir URL del recurso producto en catalogo-service
        url_cat = f"{str(settings.catalogo_url).rstrip('/')}/v1/productos/{payload.sku}"
        # Realizar petición GET asíncrona aplicando el timeout específico de catálogo
        resp_cat = await client.get(url_cat, timeout=settings.timeout_catalogo_seconds)
        
        # Verificar respuesta HTTP exitosa (200 OK)
        if resp_cat.status_code == 200:
            data_cat = resp_cat.json()
            # El producto debe tener la bandera publicado en True
            if data_cat.get("publicado") is True:
                # Obtener precio unitario en pesos colombianos
                precio_cop = float(data_cat.get("precio_cop", 0))
                # Calcular el monto total (precio * cantidad) redondeado a entero
                monto_cop = int(round(precio_cop * payload.cantidad))
                # Registrar paso exitoso en la bitácora
                pasos.append(PasoResultado(
                    paso="catalogo",
                    resultado="OK",
                    detalle=f"Producto {payload.sku} verificado y publicado (precio: {precio_cop}, monto: {monto_cop})"
                ))
            else:
                # Si el producto existe pero está despublicado, se detiene la saga
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="catalogo",
                    resultado="FALLIDO",
                    detalle=f"Producto {payload.sku} no se encuentra publicado"
                ))
        else:
            # Si catálogo devuelve 404 u otro error HTTP
            saga_exitosa = False
            pasos.append(PasoResultado(
                paso="catalogo",
                resultado="FALLIDO",
                detalle=f"Catálogo respondió HTTP {resp_cat.status_code}"
            ))
    except Exception as exc:
        # Atrapa excepciones de red, conexión rechazada o timeout (Fail-Fast)
        saga_exitosa = False
        pasos.append(PasoResultado(
            paso="catalogo",
            resultado="FALLIDO",
            detalle=f"Error o timeout en catálogo: {exc.__class__.__name__}"
        ))

    # -------------------------------------------------------------
    # PASO 2: Inventario (Reservar unidades de stock)
    # -------------------------------------------------------------
    if saga_exitosa:
        try:
            # Construir URL del endpoint de reservas de inventario
            url_inv = f"{str(settings.inventario_url).rstrip('/')}/v1/reservas"
            # Preparar payload JSON con el SKU, la cantidad y el ID de correlación
            body_inv = {
                "sku": payload.sku,
                "cantidad": payload.cantidad,
                "pedido_id": correlation_id,
            }
            # Enviar Idempotency-Key derivada para evitar reservas duplicadas ante reintentos
            headers_inv = {"Idempotency-Key": f"{idempotency_key}-reserva"}
            # Ejecutar POST asíncrono con timeout de inventario
            resp_inv = await client.post(
                url_inv,
                json=body_inv,
                headers=headers_inv,
                timeout=settings.timeout_inventario_seconds,
            )
            # Evaluar si la reserva fue creada exitosamente (200 o 201)
            if resp_inv.status_code in (200, 201):
                data_inv = resp_inv.json()
                # Extraer o generar el ID identificador de la reserva
                reserva_id = str(data_inv.get("reserva_id", f"res-{uuid.uuid4().hex[:6]}"))
                pasos.append(PasoResultado(
                    paso="inventario",
                    resultado="OK",
                    detalle=f"Reserva {reserva_id} confirmada"
                ))
            elif resp_inv.status_code == 409:
                # Código 409 Conflict: no hay stock suficiente para suplir la cantidad
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="inventario",
                    resultado="FALLIDO",
                    detalle="Stock insuficiente (HTTP 409)"
                ))
            else:
                # Otro código inesperado de error en inventario
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="inventario",
                    resultado="FALLIDO",
                    detalle=f"Inventario respondió HTTP {resp_inv.status_code}"
                ))
        except Exception as exc:
            # Captura fallos de conectividad o timeout hacia inventario
            saga_exitosa = False
            pasos.append(PasoResultado(
                paso="inventario",
                resultado="FALLIDO",
                detalle=f"Error o timeout en inventario: {exc.__class__.__name__}"
            ))

    # -------------------------------------------------------------
    # PASO 3: Pedidos (Crear registro formal del pedido)
    # -------------------------------------------------------------
    if saga_exitosa:
        try:
            # Construir URL para creación de pedidos
            url_ped = f"{str(settings.pedidos_url).rstrip('/')}/v1/pedidos"
            # Cuerpo con los datos consolidados del pedido
            body_ped = {
                "cliente_id": payload.cliente_id,
                "sku": payload.sku,
                "cantidad": payload.cantidad,
                "monto_cop": monto_cop,
            }
            # Ejecutar POST al servicio de pedidos con timeout individual
            resp_ped = await client.post(
                url_ped,
                json=body_ped,
                timeout=settings.timeout_pedidos_seconds,
            )
            # Evaluar creación satisfactoria (200 o 201)
            if resp_ped.status_code in (200, 201):
                data_ped = resp_ped.json()
                # Actualizar pedido_id con el ID oficial generado por el servicio de Pedidos
                pedido_id = str(data_ped.get("pedido_id", correlation_id))
                pasos.append(PasoResultado(
                    paso="pedidos",
                    resultado="OK",
                    detalle=f"Pedido {pedido_id} creado en estado {data_ped.get('estado', 'CREADO')}"
                ))
            else:
                # Falló la creación del pedido
                saga_exitosa = False
                pasos.append(PasoResultado(
                    paso="pedidos",
                    resultado="FALLIDO",
                    detalle=f"Pedidos respondió HTTP {resp_ped.status_code}"
                ))
        except Exception as exc:
            # Timeout o error de red hacia el servicio de pedidos
            saga_exitosa = False
            pasos.append(PasoResultado(
                paso="pedidos",
                resultado="FALLIDO",
                detalle=f"Error o timeout en pedidos: {exc.__class__.__name__}"
            ))

    # -------------------------------------------------------------
    # PASO 4: Pagos (Efectuar cobro del monto total)
    # -------------------------------------------------------------
    if saga_exitosa:
        try:
            # URL del endpoint de procesamiento de pagos
            url_pag = f"{str(settings.pagos_url).rstrip('/')}/v1/pagos"
            # Datos de pago vinculados al pedido oficial
            body_pag = {
                "pedido_id": pedido_id,
                "monto_cop": monto_cop,
                "medio": payload.medio_pago,
            }
            # Idempotency-Key derivada para proteger contra cobros dobles en la pasarela
            headers_pag = {"Idempotency-Key": f"{idempotency_key}-pago"}
            # Ejecutar llamada asíncrona de cobro con timeout de pagos
            resp_pag = await client.post(
                url_pag,
                json=body_pag,
                headers=headers_pag,
                timeout=settings.timeout_pagos_seconds,
            )
            # Verificar si el servicio de pagos respondió con código de éxito
            if resp_pag.status_code in (200, 201):
                data_pag = resp_pag.json()
                # Extraer el ID único de la transacción de pago
                pago_id = str(data_pag.get("pago_id", f"pag-{uuid.uuid4().hex[:6]}"))
                # Normalizar el estado devuelto (ej. APROBADO, PENDIENTE, RECHAZADO)
                estado_pago = str(data_pag.get("estado", "")).upper()
                
                if estado_pago == "APROBADO":
                    # Pago completado exitosamente: si algo fallara posterior requeriría reembolso
                    pago_requiere_reembolso = True
                    pasos.append(PasoResultado(
                        paso="pagos",
                        resultado="OK",
                        detalle=f"Pago {pago_id} APROBADO"
                    ))
                elif estado_pago == "PENDIENTE":
                    # Pago pendiente: la política del parcial exige tratarlo como fallo y cancelar/reembolsar
                    saga_exitosa = False
                    pago_requiere_reembolso = True
                    pasos.append(PasoResultado(
                        paso="pagos",
                        resultado="FALLIDO",
                        detalle=f"Pago {pago_id} en estado PENDIENTE (se trata como fallo y requiere reembolso/cancelación)"
                    ))
                else:
                    # Pago RECHAZADO: la transacción fue denegada (no hay fondos debitados, no requiere reembolso)
                    saga_exitosa = False
                    pago_requiere_reembolso = False
                    pasos.append(PasoResultado(
                        paso="pagos",
                        resultado="FALLIDO",
                        detalle=f"Pago {pago_id} RECHAZADO (no cobrado, no requiere reembolso)"
                    ))
            else:
                # El servicio de pagos devolvió error HTTP
                saga_exitosa = False
                pago_requiere_reembolso = False
                pasos.append(PasoResultado(
                    paso="pagos",
                    resultado="FALLIDO",
                    detalle=f"Pagos respondió HTTP {resp_pag.status_code}"
                ))
        except Exception as exc:
            # Fallo o timeout al contactar la pasarela de pagos
            saga_exitosa = False
            pago_requiere_reembolso = False
            pasos.append(PasoResultado(
                paso="pagos",
                resultado="FALLIDO",
                detalle=f"Error o timeout en pagos: {exc.__class__.__name__}"
            ))

    # -------------------------------------------------------------
    # COMPENSACIONES (Transacciones compensatorias en orden inverso)
    # -------------------------------------------------------------
    if not saga_exitosa:
        # Compensación 4 -> Reembolsar dinero si se alcanzó a procesar un pago con cobro
        if pago_id and pago_requiere_reembolso:
            try:
                # URL de compensación del servicio de pagos
                url_reemb = f"{str(settings.pagos_url).rstrip('/')}/v1/pagos/{pago_id}/reembolso"
                # Cabecera de idempotencia para la operación de reembolso
                headers_reemb = {"Idempotency-Key": f"{idempotency_key}-reembolso"}
                # Ejecutar solicitud POST para revertir el cargo financiero
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
                # Registrar si la compensación de pago falló para auditoría
                pasos.append(PasoResultado(
                    paso="pagos_reembolso",
                    resultado="FALLIDO",
                    detalle=f"Error al reembolsar {pago_id}: {exc.__class__.__name__}"
                ))

        # Compensación 3 -> Cancelar el pedido si alcanzó a ser creado en el servicio de Pedidos
        if pedido_id and pedido_id != correlation_id:
            try:
                # URL del endpoint de cancelación en pedidos-service
                url_canc = f"{str(settings.pedidos_url).rstrip('/')}/v1/pedidos/{pedido_id}/cancelar"
                # Disparar la cancelación del pedido
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
                # Registrar error si la cancelación no pudo completarse
                pasos.append(PasoResultado(
                    paso="pedidos_cancelar",
                    resultado="FALLIDO",
                    detalle=f"Error al cancelar pedido {pedido_id}: {exc.__class__.__name__}"
                ))

        # Compensación 2 -> Liberar unidades de stock reservadas en Inventario
        if reserva_id:
            try:
                # URL del endpoint de liberación de reservas en inventario-service
                url_lib = f"{str(settings.inventario_url).rstrip('/')}/v1/reservas/{reserva_id}/liberar"
                # Idempotency-Key para garantizar que la liberación sea idempotente
                headers_lib = {"Idempotency-Key": f"{idempotency_key}-liberar"}
                # Disparar la liberación del stock
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
                # Registrar error si falló la liberación de la reserva
                pasos.append(PasoResultado(
                    paso="inventario_liberar",
                    resultado="FALLIDO",
                    detalle=f"Error al liberar reserva {reserva_id}: {exc.__class__.__name__}"
                ))

    # Determinar el estado final consolidado de la saga
    estado_final = "CONFIRMADO" if saga_exitosa else "FALLIDO"
    # Construir y retornar el DTO de respuesta con el pedido_id y el historial de pasos
    return CheckoutResponse(
        pedido_id=pedido_id,
        estado=estado_final,
        pasos=pasos,
    )
