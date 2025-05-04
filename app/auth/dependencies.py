from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import ValidationError
from datetime import datetime, timedelta

from .security import (
    SECRET_KEY, ALGORITHM, fake_users_db, User, TokenData,
    authenticate_user, create_access_token
)

# Definir el esquema OAuth2 para la autenticación con token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Función para obtener el usuario actual a partir del token
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Decodificar el token JWT
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except (JWTError, ValidationError):
        raise credentials_exception

    # Obtener el usuario de la "base de datos"
    user = None
    if token_data.username in fake_users_db:
        user_dict = fake_users_db[token_data.username]
        user = User(
            username=user_dict["username"],
            disabled=user_dict.get("disabled", False)
        )

    if user is None:
        raise credentials_exception

    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )

    return user

# Función para obtener el usuario activo (adicional para verificar estado de usuario)
async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Usuario inactivo")
    return current_user
