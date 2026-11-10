import httpx
from app.settings import get_settings

settings = get_settings()

class PasarelaACL:
    @staticmethod
    async def cobrar(monto: float, medio: str) -> str:
        url = "http://localhost:8004/_simulador/pasarela/cobrar"
        timeout = httpx.Timeout(settings.http_timeout_seconds)
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url, 
                    json={"monto": float(monto), "medio": medio, "modo": settings.pasarela_modo}
                )
                if response.status_code == 504:
                    return "PENDIENTE"
                if response.status_code != 200:
                    return "RECHAZADO"
                
                data = response.json()
                ext_status = data.get("status", "DECLINED")
                
                # Traducción ACL: vocabulario externo -> vocabulario del dominio
                if ext_status == "APPROVED":
                    return "APROBADO"
                elif ext_status == "DECLINED":
                    return "RECHAZADO"
                else:
                    return "PENDIENTE"
        except (httpx.TimeoutException, httpx.RequestError):
            return "PENDIENTE"