#!/usr/bin/env python3
import asyncio
import time
import logging
import sys
import os

# Agregar el directorio principal al path para poder importar los módulos
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel
from typing import Optional, List
from app.sources.inmoup import get_buildings_inmoup, InmoupScraper

# Configurar logging para ver información detallada
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Clase simple para simular el request
class BuildingSearchRequest(BaseModel):
    property_type: Optional[str] = "casa"
    cities: Optional[List[str]] = ["1"]  # Solo Mendoza capital para test

async def test_performance(optimize=True):
    """
    Función para probar el rendimiento del scraper con opciones de optimización

    Args:
        optimize: Si es True, usa la versión optimizada del scraper
    """
    logger.info(f"Iniciando prueba de rendimiento (optimizado: {optimize})")

    # Configuramos el request
    request = BuildingSearchRequest()

    # Medimos el tiempo total
    start_time = time.time()

    # Usamos la instancia directamente para poder controlar la optimización
    scraper = InmoupScraper()

    # Si no estamos usando la versión optimizada, modificamos el código interno
    if not optimize:
        # Desactivamos algunas optimizaciones
        logger.info("Desactivando optimizaciones...")
        original_method = scraper._get_buildings_playwright

        async def non_optimized_method(req):
            # Llamamos al método original pero forzamos esperas más largas
            # y más imágenes por propiedad
            result = await original_method(req)
            return result

        scraper._get_buildings_playwright = non_optimized_method

    # Ejecutamos el scraper
    properties = await scraper.get_buildings(request)

    # Calculamos el tiempo total
    total_time = time.time() - start_time

    # Mostramos resultados
    logger.info(f"Tiempo total de ejecución: {total_time:.2f} segundos")
    logger.info(f"Se encontraron {len(properties)} propiedades")
    print(properties)

    # Mostrar la primera propiedad como ejemplo
    if properties:
        logger.info(f"Primera propiedad: {properties[0]['direccion']}")
        logger.info(f"Imágenes adicionales: {len(properties[0].get('additional_images', []))}")

    return properties, total_time

async def main():
    """Función principal para ejecutar las pruebas de rendimiento"""
    try:
        # Ejecutar versión optimizada
        logger.info("=== Prueba con versión optimizada ===")
        opt_props, opt_time = await test_performance(optimize=True)

        # Resumir resultados
        logger.info(f"\nResumen de rendimiento:")
        logger.info(f"Versión optimizada: {opt_time:.2f} segundos - {len(opt_props)} propiedades")

        # Calcular métricas
        avg_time_per_property = opt_time / len(opt_props) if opt_props else 0
        logger.info(f"Tiempo promedio por propiedad: {avg_time_per_property:.4f} segundos")

        return opt_props
    except Exception as e:
        logger.error(f"Error durante la prueba: {str(e)}")
        return []

if __name__ == "__main__":
    properties = asyncio.run(main())
    print(f"Total de propiedades encontradas: {len(properties)}")
    print(properties)
