from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from jose import JWTError, jwt
import os
import json
import base64
from passlib.context import CryptContext
from dotenv import load_dotenv
from fastapi import Request, HTTPException, status
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

# Configuración para JWT desde variables de entorno
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default_insecure_key")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

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

# Función para descifrar texto con formato personalizado simple
def decrypt_custom_format(encrypted_text):
    try:
        logger.info(f"Procesando formato personalizado: {encrypted_text[:15]}...")

        # Verificar si tiene el prefijo que indica nuestro formato personalizado
        if encrypted_text.startswith("CUSTOM_ENC:"):
            # Extraer la parte codificada en base64
            base64_part = encrypted_text[10:]  # Quitar "CUSTOM_ENC:"

            # Decodificar de base64 a texto plano
            plaintext = base64.b64decode(base64_part).decode('utf-8')

            logger.info(f"Descifrado exitoso usando formato personalizado")
            return plaintext
        else:
            # Si no tiene el prefijo esperado, intentar otros métodos
            raise ValueError("No es un formato personalizado reconocido")

    except Exception as e:
        logger.error(f"Error al procesar formato personalizado: {str(e)}")
        raise

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
    logger.info("Autenticando usuario con credenciales procesadas")

    username = form_data.get('username', '')
    encrypted_password = form_data.get('password', '')
    password = ""

    # Verificar si es nuestro formato personalizado
    if encrypted_password.startswith("CUSTOM_ENC:"):
        try:
            logger.info("Detectado formato personalizado")
            password = decrypt_custom_format(encrypted_password)
            logger.info(f"Contraseña descifrada: {password[:2]}***")
        except Exception as e:
            logger.error(f"Error al procesar formato personalizado: {str(e)}")
            # En caso de error, usar la contraseña sin procesar
            password = encrypted_password
    else:
        # Si no está cifrada, usar directamente
        password = encrypted_password
        logger.info("Usando contraseña sin cifrar")

    # Autenticar con las credenciales procesadas
    logger.info(f"Intentando autenticar usuario: {username}")
    user = authenticate_user(fake_db, username, password)
    if not user:
        logger.warning(f"Autenticación fallida para el usuario: {username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(f"Usuario autenticado correctamente: {username}")
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
