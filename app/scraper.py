import logging
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Dict, Type
from .sources import BaseScraper, InmoupScraper, MendozaPropScraper

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ScraperFactory:
    """
    Factory para crear instancias de scrapers basados en la fuente solicitada
    Implementa el patrón factory para crear los scrapers apropiados
    """

    # Registro de scrapers disponibles
    _scrapers: Dict[str, Type[BaseScraper]] = {
        "inmoup": InmoupScraper,
        "mendozaprop": MendozaPropScraper
    }

    @classmethod
    def get_scraper(cls, source: str) -> BaseScraper:
        """
        Obtiene una instancia del scraper adecuado según la fuente

        Args:
            source: Nombre de la fuente (ej. "inmoup")

        Returns:
            Una instancia del scraper correspondiente

        Raises:
            HTTPException: Si la fuente no está soportada
        """
        source_lower = source.lower() if source else ""

        if source_lower in cls._scrapers:
            # Crear y devolver una instancia del scraper correspondiente
            return cls._scrapers[source_lower]()
        else:
            logger.error(f"Source no soportada: {source}")
            raise HTTPException(
                status_code=400,
                detail=f"Source no soportada: {source}"
            )

    @classmethod
    def register_scraper(cls, source_name: str, scraper_class: Type[BaseScraper]) -> None:
        """
        Registra un nuevo tipo de scraper en la factory

        Args:
            source_name: Nombre de la fuente (ej. "zonaprop")
            scraper_class: Clase del scraper que implementa BaseScraper
        """
        cls._scrapers[source_name.lower()] = scraper_class

# Función principal que recibe el request completo y usa el factory para obtener el scraper adecuado
async def get_buildings(request: BaseModel):
    """
    Obtiene edificios basados en los parámetros de request usando inversión de dependencia

    Args:
        request: Objeto BuildingSearchRequest con source, province, cities y property_type

    Returns:
        Lista de propiedades encontradas
    """
    logger.info(f"Buscando propiedades con: {request}")

    # Obtener el scraper apropiado usando el factory
    scraper = ScraperFactory.get_scraper(request.source)

    # Usar el scraper para obtener los edificios
    return await scraper.get_buildings(request)
