# Mapea Backend

API de backend para la aplicación Mapea, desarrollada con FastAPI. Proporciona endpoints para buscar y filtrar propiedades inmobiliarias de diversas fuentes.

## Características

- API RESTful con FastAPI
- Autenticación JWT para endpoints protegidos
- Integración con múltiples fuentes de datos inmobiliarios
- Rate limiting para protección contra abusos
- Middleware CORS configurado para seguridad

## Requisitos

- Python 3.10+
- Dependencias listadas en requirements.txt

## Instalación

```bash
# Clonar el repositorio
git clone https://github.com/tincho-aguilera/mapea-back.git
cd mapea-back

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
```

## Variables de entorno

Crea un archivo `.env` basado en `.env.example` con las siguientes variables:

```
JWT_SECRET_KEY=tu_clave_secreta_aqui
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
API_USERNAME=tu_usuario
API_PASSWORD=tu_contraseña
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False
ALLOWED_ORIGINS=https://mapea-kappa.vercel.app
```

## Desarrollo

Para ejecutar en modo desarrollo:

```bash
uvicorn app.main:app --reload
```

La documentación de la API estará disponible en:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Despliegue

Este backend está configurado para despliegues en plataformas como:
- Railway
- Render
- Fly.io

Usa el Procfile incluido para definir el proceso web.

## Endpoints principales

- `POST /api/properties/search`: Buscar propiedades con filtros
- `GET /api/inmoup/zonas`: Obtener zonas disponibles en InmouP
- `POST /token`: Obtener token JWT para autenticación
- `GET /users/me`: Verificar usuario autenticado
- `GET /health`: Endpoint de verificación de salud

## Licencia

MIT
