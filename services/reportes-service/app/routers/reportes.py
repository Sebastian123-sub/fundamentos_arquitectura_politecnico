"""Rutas CRUD para el servicio de reportes."""
# Tipo que representa la lista de reportes devuelta por la consulta. P10
from collections.abc import Sequence

# APIRouter agrupa direcciones; Depends permite pedir recursos automaticamente. P10
from fastapi import APIRouter, Depends
# select prepara una consulta para leer datos de la tabla. P10
from sqlalchemy import select
# Tipo de sesion usada para comunicarse con la base de datos. P10
from sqlalchemy.ext.asyncio import AsyncSession

# Funcion que entrega una sesion de base de datos a cada solicitud. P10
from app.database import get_db
# Modelo de tabla y formatos de datos de entrada y salida. P10
from app.models import ReporteModel
from app.schemas import ReporteCreate, ReporteResponse

# Todas las direcciones de este grupo comienzan con /reportes. P10
router = APIRouter(prefix="/reportes", tags=["reportes"])


# Recibe los datos de un reporte y devuelve el reporte ya guardado. P10
@router.post("/", response_model=ReporteResponse)
async def crear_reporte(
    # FastAPI revisa que los datos tengan la forma esperada. P10
    reporte: ReporteCreate,
    # FastAPI abre y entrega una sesion para guardar la informacion. P10
    db: AsyncSession = Depends(get_db),
) -> ReporteModel:
    # Convierte los datos recibidos en un objeto que representa una fila. P10
    nuevo = ReporteModel(**reporte.model_dump())
    # Agrupa el guardado para que se complete como una sola operacion. P10
    async with db.begin():
        # Agrega el nuevo reporte para que se guarde. P10
        db.add(nuevo)
        # Envia el guardado a la base para obtener los valores generados. P10
        await db.flush()
        # Actualiza el objeto con los datos que quedaron guardados. P10
        await db.refresh(nuevo)
    # Devuelve el reporte creado. P10
    return nuevo


# Devuelve todos los reportes que estan guardados. P10
@router.get("/", response_model=list[ReporteResponse])
async def listar_reportes(
    # Obtiene una sesion para consultar la base de datos. P10
    db: AsyncSession = Depends(get_db),
) -> Sequence[ReporteModel]:
    # Prepara y ejecuta una consulta de todos los reportes. P10
    result = await db.execute(select(ReporteModel))
    # Extrae los reportes encontrados y los devuelve como una lista. P10
    return result.scalars().all()