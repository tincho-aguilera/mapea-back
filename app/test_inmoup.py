#!/usr/bin/env python3
import asyncio
import logging
from pydantic import BaseModel
from typing import Optional, List
import sys
import os
import time  # Agregamos el módulo time para medir el rendimiento

# Configurar logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Agregar el directorio principal al path para poder importar los módulos
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importar el scraper
from sources.inmoup import InmoupScraper, get_buildings_inmoup

# Clase simple para simular el request
class BuildingSearchRequest(BaseModel):
    property_type: Optional[str] = "casa"
    cities: Optional[List[str]] = ["1"]

async def test_inmoup_scraper():
    logger.info("Iniciando prueba del scraper de Inmoup")

    # Medimos el tiempo de inicio
    start_time = time.time()

    # Opción 1: Usar la función auxiliar
    logger.info("Probando con la función auxiliar get_buildings_inmoup")
    request = BuildingSearchRequest()
    properties = await get_buildings_inmoup(request)

    # Calculamos el tiempo transcurrido
    elapsed_time = time.time() - start_time
    logger.info(f"Tiempo de respuesta: {elapsed_time:.2f} segundos")

    logger.info(f"Se encontraron {len(properties)} propiedades con la función auxiliar")

    # Imprimir la primera propiedad como ejemplo
    if properties:
        logger.info(f"Ejemplo de propiedad: {properties[0]}")
    else:
        logger.info("No se encontraron propiedades")

    # Opción 2: Usar la clase directamente
    # logger.info("Probando con la clase InmoupScraper")
    # scraper = InmoupScraper()
    # properties = await scraper.get_buildings(request)
    # logger.info(f"Se encontraron {len(properties)} propiedades con la clase")

    return properties

async def main():
    try:
        start_time = time.time()  # Tiempo de inicio global
        properties = await test_inmoup_scraper()
        total_time = time.time() - start_time  # Tiempo total
        logger.info(f"Tiempo total de ejecución: {total_time:.2f} segundos")
        logger.info("Prueba completada con éxito")
        return properties, total_time  # Devolvemos también el tiempo
    except Exception as e:
        logger.error(f"Error durante la prueba: {str(e)}")
        return [], 0

if __name__ == "__main__":
    properties, total_time = asyncio.run(main())
    # Imprimir el número total de propiedades encontradas
    print(f"Total de propiedades encontradas: {len(properties)}")
    print(f"Tiempo total de ejecución: {total_time:.2f} segundos")
    print("Propiedades:", properties)
