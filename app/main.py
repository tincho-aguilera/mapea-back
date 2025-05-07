from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Depends, status, Form, Header
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware import Middleware
from .scraper import get_buildings
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import uvicorn
import logging
import requests
import os
import time
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
from typing import Optional

# Importaciones para autenticación
from .auth.security import (
    Token, User, authenticate_user, authenticate_user_processed, create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES, fake_users_db
)
from .auth.dependencies import get_current_active_user

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Implementación de rate limiting middleware
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests=100, window_seconds=60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_counts = defaultdict(list)

    async def dispatch(self, request, call_next):
        # Obtener la IP del cliente
        client_ip = request.client.host

        # Limpiar entradas antiguas
        current_time = time.time()
        self.request_counts[client_ip] = [
            timestamp for timestamp in self.request_counts[client_ip]
            if timestamp > current_time - self.window_seconds
        ]

        # Verificar si el cliente excedió el límite
        if len(self.request_counts[client_ip]) >= self.max_requests:
            return self._rate_limit_response()

        # Registrar la solicitud actual
        self.request_counts[client_ip].append(current_time)

        # Procesar la solicitud normalmente
        response = await call_next(request)
        return response

    def _rate_limit_response(self):
        from starlette.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Demasiadas solicitudes. Por favor, intente más tarde."}
        )

class BuildingSearchRequest(BaseModel):
    source: str
    province: str
    cities: list[str]
    property_type: str

app = FastAPI(
    title="Alquileres Scraper API",
    description="API para obtener datos de alquileres de diferentes sitios web",
    version="1.0.0"
)

# Agregar middleware de rate limiting
app.add_middleware(
    RateLimitMiddleware,
    max_requests=100,  # Número máximo de solicitudes por ventana de tiempo
    window_seconds=60  # Ventana de tiempo en segundos
)

# Obtener orígenes permitidos desde variables de entorno o usar valores predeterminados seguros
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174").split(",")

# Configurar CORS para permitir peticiones solo desde orígenes específicos
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)

@app.get("/")
async def root():
    return {
        "message": "Bienvenido a la API de Scraper de Alquileres. "
                   "Usá /api/properties/search para consultar propiedades."
    }

# Endpoint para obtener token JWT (versión simplificada)
@app.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None)
):
    """
    Endpoint para autenticación y obtención de token JWT.
    Soporta autenticación estándar o con ofuscación básica.
    """
    logger.info("Iniciando proceso de autenticación")
    start_time = time.time()
    logger.info(f"Datos de entrada: username={username}, password={password}")
    # Crear un diccionario con los datos del formulario
    form_data = {
        "username": username,
        "password": password
    }

    # Usar la función para autenticar con credenciales procesadas
    user = authenticate_user_processed(fake_users_db, form_data, request)

    auth_time = time.time() - start_time
    logger.info(f"Autenticación completada en {auth_time:.2f} segundos")

    # Crear token de acceso (JWT)
    token_start = time.time()
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )

    token_time = time.time() - token_start
    total_time = time.time() - start_time
    logger.info(f"Token generado en {token_time:.2f} segundos. Tiempo total: {total_time:.2f} segundos")

    return {"access_token": access_token, "token_type": "bearer"}

# Endpoint para verificar el token y usuario actual
@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """
    Endpoint para verificar la autenticación del usuario actual.
    """
    return current_user

@app.post("/api/properties/search")
async def search_properties(
    request: BuildingSearchRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Consulta propiedades disponibles en diferentes fuentes según filtros de búsqueda.
    Actualmente soporta: inmoup, mendozaprop
    Aunque se usa POST por compatibilidad con navegadores, esta operación es solo de lectura.
    """
    try:
        logger.info(f"Consulta recibida: source={request.source}, province={request.province}, cities={request.cities}, property_type={request.property_type}")
        buildings = await get_buildings(request=request)
        logger.info(f"{len(buildings)} propiedades encontradas")
        return buildings
    except HTTPException as e:
        # Mantener la excepción HTTP ya formateada correctamente
        logger.error(f"Error HTTP desde el scraper: {e.detail}")
        raise
    except Exception as e:
        # Registrar el error completo pero no exponer detalles al cliente
        logger.error(f"Error inesperado: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor al procesar la solicitud"
        )

@app.get("/api/inmoup/zonas")
async def get_inmoup_zonas(current_user: User = Depends(get_current_active_user)):
    """
    Endpoint proxy para obtener las zonas desde Inmoup
    """
    try:
        # URL fija para evitar ataques SSRF
        inmoup_url = "https://www.inmoup.com.ar/zonas"
        params = {"pai_id": 1}

        # Configurar tiempos de espera para evitar bloqueos
        timeout_seconds = 10

        # Hacer la petición con parámetros validados y timeout
        response = requests.get(
            inmoup_url,
            params=params,
            timeout=timeout_seconds,
            headers={
                "User-Agent": "AlquileresScraper/1.0"
            }
        )

        if response.status_code == 200:
            return response.json()
        else:
            # Registrar el error pero no mostrar detalles al cliente
            logger.error(f"Error en petición a Inmoup: {response.status_code}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error al obtener datos del servicio externo"
            )
    except requests.Timeout:
        logger.error("Timeout en la petición a Inmoup")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Tiempo de espera agotado al conectar con el servicio externo"
        )
    except Exception as e:
        # Registrar el error pero no mostrar detalles al cliente
        logger.error(f"Error al conectar con Inmoup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al procesar la solicitud"
        )

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
