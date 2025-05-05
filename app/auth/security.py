from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from jose import JWTError, jwt
import os
import json
import base64
import secrets
from passlib.context import CryptContext
from dotenv import load_dotenv
from fastapi import Request, HTTPException, status
import logging

# Cargar variables de entorno
load_dotenv()

# Configuración para JWT desde variables de entorno
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default_insecure_key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# Configuración para tokens CSRF
CSRF_TOKEN_EXPIRE_HOURS = int(os.getenv("CSRF_TOKEN_EXPIRE_HOURS", "24"))
CSRF_ENABLED = os.getenv("CSRF_ENABLED", "true").lower() == "true"
CSRF_ALLOWED_ORIGINS = os.getenv("CSRF_ALLOWED_ORIGINS", "*").split(",")

# Modelo de usuario simplificado para autenticación interna
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class User(BaseModel):
    username: str
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

# Configuración de hash de contraseña
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Función para verificar contraseñas
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Función para hash de contraseña
def get_password_hash(password):
    return pwd_context.hash(password)

# Base de datos simulada para usuarios internos desde variables de entorno
API_USERNAME = os.getenv("API_USERNAME", "admin")
API_PASSWORD = os.getenv("API_PASSWORD", "insecure_default_password")

fake_users_db = {
    API_USERNAME: {
        "username": API_USERNAME,
        "hashed_password": get_password_hash(API_PASSWORD),
        "disabled": False,
    }
}

# Configurar logging
logger = logging.getLogger(__name__)

# Diccionario para almacenar tokens CSRF con TTL
csrf_tokens = {}

# Función para limpiar tokens expirados (llamada periódicamente)
def clean_expired_csrf_tokens():
    current_time = datetime.utcnow()
    expired_tokens = [token for token, data in csrf_tokens.items() 
                      if current_time > data.get('expires_at', current_time)]
    for token in expired_tokens:
        csrf_tokens.pop(token, None)

# Función para generar un token CSRF
def generate_csrf_token():
    token = secrets.token_hex(32)
    # Usar la duración configurada en las variables de entorno
    expires_at = datetime.utcnow() + timedelta(hours=CSRF_TOKEN_EXPIRE_HOURS)
    csrf_tokens[token] = {
        'created_at': datetime.utcnow(),
        'expires_at': expires_at,
    }
    return token

# Función para verificar token CSRF
def verify_csrf_token(token: str, request: Request) -> bool:
    # Si CSRF está desactivado, siempre retornar válido
    if not CSRF_ENABLED:
        return True
        
    # Limpiar tokens expirados primero
    clean_expired_csrf_tokens()
    
    # Si no hay token, considerarlo válido temporalmente para compatibilidad
    # TODO: Hacer esto obligatorio una vez que el frontend esté actualizado completamente
    if not token:
        return True

    # Para desarrollo local, siempre considerar válido si es localhost
    client_host = request.client.host if request.client else None
    if client_host in ["127.0.0.1", "localhost", "::1"]:
        return True
    
    # Verificar si el referer está en los orígenes permitidos
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if origin and CSRF_ALLOWED_ORIGINS != ["*"]:
        is_allowed_origin = False
        for allowed_origin in CSRF_ALLOWED_ORIGINS:
            if allowed_origin in origin:
                is_allowed_origin = True
                break
        if not is_allowed_origin:
            logger.warning(f"Origen no permitido para CSRF: {origin}")
            return False
    
    # En producción, verificar si el token existe y no ha expirado
    token_data = csrf_tokens.get(token)
    if token_data and datetime.utcnow() <= token_data.get('expires_at'):
        # No eliminamos el token después de validarlo para permitir
        # múltiples intentos en aplicaciones SPA o peticiones ajax
        return True
        
    # Registrar el error para debugging
    logger.warning(f"CSRF token inválido o expirado: {token}")
    return False

# Función para decodificar credenciales en base64
def decode_base64_credentials(username_b64: str, password_b64: str) -> tuple:
    try:
        username = base64.b64decode(username_b64).decode('utf-8')
        password = base64.b64decode(password_b64).decode('utf-8')
        return username, password
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error en la decodificación de credenciales"
        )

# Función para procesar una solicitud de autenticación segura
def process_secure_auth(secure_auth_json: str) -> tuple:
    try:
        # Convertir la cadena JSON a diccionario
        secure_auth = json.loads(secure_auth_json)

        # Extraer username y password
        username_b64 = secure_auth.get('username')
        password_b64 = secure_auth.get('password')

        # Decodificar si es necesario
        if secure_auth.get('encrypted'):
            # Aquí implementaríamos descifrado con clave privada si fuera necesario
            pass

        # Por ahora, simplemente decodificamos de base64
        return decode_base64_credentials(username_b64, password_b64)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error procesando autenticación segura: {str(e)}"
        )

# Función para obtener un usuario
def get_user(db, username: str):
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)
    return None

# Función para autenticar usuario
def authenticate_user(fake_db, username: str, password: str):
    user = get_user(fake_db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

# Función para autenticar usuario con credenciales procesadas
def authenticate_user_processed(fake_db, form_data, request: Request):
    # Verificar si se incluye token CSRF
    csrf_token = form_data.get('csrf_token') or request.headers.get('X-CSRF-Token')

    # Si hay token CSRF, verificarlo
    if csrf_token and not verify_csrf_token(csrf_token, request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF inválido o expirado"
        )

    # Verificar si las credenciales vienen en modo seguro
    if 'secure_auth' in form_data:
        username, password = process_secure_auth(form_data.get('secure_auth'))
    else:
        # Verificar si las credenciales están codificadas en base64
        if form_data.get('encoding') == 'base64':
            username, password = decode_base64_credentials(
                form_data.get('username', ''),
                form_data.get('password', '')
            )
        else:
            # Autenticación estándar
            username = form_data.get('username', '')
            password = form_data.get('password', '')

    # Autenticar con las credenciales procesadas
    user = authenticate_user(fake_db, username, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

# Función para crear un token de acceso
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
