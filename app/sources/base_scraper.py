from abc import ABC, abstractmethod
import logging
from typing import List, Dict, Any
from pydantic import BaseModel

# Configurar logging
logger = logging.getLogger(__name__)

class BaseScraper(ABC):
    """
    Clase base abstracta que define la interfaz para todos los scrapers de propiedades
    """

    @abstractmethod
    async def get_buildings(self, request: BaseModel) -> List[Dict[str, Any]]:
        """
        Método abstracto que debe ser implementado por las clases concretas
        para obtener propiedades de una fuente específica

        Args:
            request: Objeto con los parámetros de búsqueda

        Returns:
            Lista de propiedades encontradas
        """
        pass
