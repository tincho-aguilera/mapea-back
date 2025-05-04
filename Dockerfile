FROM mcr.microsoft.com/playwright/python:v1.41.1-jammy

# Establecer directorio de trabajo
WORKDIR /app

# Copiar archivos de la aplicación
COPY . /app

# Instalar dependencias
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Exponer puerto
EXPOSE 8000

# Comando para iniciar la app con uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
