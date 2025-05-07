from playwright.async_api import async_playwright
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
from .base_scraper import BaseScraper
import asyncio
import json
import re
import os
from bs4 import BeautifulSoup

# Configurar logging
logger = logging.getLogger(__name__)

class InmoupScraper(BaseScraper):
    """
    Scraper específico para el sitio Inmoup
    """

    def _fix_image_url(self, image_url: str) -> str:
        """
        Convierte URLs relativas de imágenes a URLs absolutas.

        Args:
            image_url: URL de la imagen, que puede ser relativa o absoluta

        Returns:
            URL absoluta de la imagen
        """
        if not image_url:
            return ""

        # Si ya es una URL absoluta, devolverla como está
        if image_url.startswith(('http://', 'https://')):
            return image_url

        # Si es una ruta relativa, añadir el dominio base de Inmoup
        return f"https://inmoup.com.ar{image_url}"

    async def get_buildings(self, request: BaseModel) -> List[Dict[str, Any]]:
        """
        Implementación del método para obtener propiedades de Inmoup

        Args:
            request: Objeto BuildingSearchRequest con los parámetros de búsqueda

        Returns:
            Lista de propiedades encontradas
        """
        try:
            # Usamos Playwright para obtener los datos de las propiedades
            return await self._get_buildings_playwright(request)
        except Exception as e:
            logger.error(f"Error general en el scraper de Inmoup: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor al procesar datos de inmuebles de Inmoup"
            )

    async def _get_buildings_playwright(self, request: Optional[BaseModel]) -> List[Dict[str, Any]]:
        """
        Implementación del método para obtener propiedades de Inmoup usando Playwright
        """
        try:
            async with async_playwright() as p:
                # Configuración adaptada para entornos como Render
                browser_type = p.chromium
                browser_launch_args = {
                    'headless': True,
                    'args': ['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage']
                }

                # Verificar si estamos en Render.com y usar un enfoque diferente
                in_render = os.environ.get('RENDER', 'false').lower() == 'true'
                if in_render:
                    # En Render, podemos usar Chrome en lugar de instalar Chromium
                    logger.info("Usando navegador para Render.com")
                    browser_type = p.chromium
                    browser_launch_args = {
                        'headless': True,
                        'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-accelerated-2d-canvas', '--disable-gpu']
                    }

                # Lanzar el navegador con la configuración adaptada
                browser = await browser_type.launch(**browser_launch_args)

                page = await browser.new_page()

                # Construir URL basada en los filtros proporcionados
                base_url = "https://inmoup.com.ar/"

                # Determinar tipo de propiedad para la URL
                prop_type = "casas-en-alquiler"
                if request and request.property_type and "depart" in request.property_type.lower():
                    prop_type = "departamentos-en-alquiler"

                url = f"{base_url}{prop_type}?favoritos=0&limit=10000&prevEstadoMap=&ordenar=recientes"

                # Añadir localidades si están especificadas
                if request and request.cities and len(request.cities) > 0:
                    # Convertir la lista de IDs de ciudades a formato de URL
                    city_ids = request.cities
                    # Si city_ids ya viene como una cadena con el formato "2,1,8", usarla directamente
                    if isinstance(city_ids, str):
                        # Reemplazamos las comas con %2C para la codificación URL
                        formatted_ids = city_ids.replace(',', '%2C')
                        url += f"&localidades={formatted_ids}"
                    else:
                        # Si es una lista, la unimos con %2C
                        formatted_ids = '%2C'.join(str(city_id) for city_id in city_ids)
                        url += f"&localidades={formatted_ids}"
                else:
                    # Valores por defecto si no se especifican ciudades
                    url += "&localidades=1%2C2%2C7%2C19"

                url += "&lastZoom=13&precio%5Bmin%5D=&precio%5Bmax%5D=&moneda=1&sup_cubierta%5Bmin%5D=&sup_cubierta%5Bmax%5D=&sup_total%5Bmin%5D=&sup_total%5Bmax%5D=&recientes=mes"

                logger.info(f"Navegando a URL con Playwright: {url}")

                # Aumentar el timeout a 60 segundos y agregar logs para debug
                logger.info("Iniciando navegación a inmoup.com.ar con Playwright")
                try:
                    # Reducir el timeout a 30 segundos para evitar bloqueos innecesariamente largos
                    await page.goto(
                        url,
                        timeout=30000,  # Reducido de 60000 a 30000 ms (30 segundos)
                        wait_until="domcontentloaded"  # Evento que permite cargar antes sin esperar recursos completos
                    )
                    logger.info("Página cargada correctamente")
                except Exception as e:
                    logger.error(f"Error durante la navegación con Playwright: {str(e)}")
                    # Mostrar un error más amigable al usuario
                    raise HTTPException(
                        status_code=503,
                        detail="No se pudo acceder a inmoup.com.ar. El sitio podría estar caído o bloqueando peticiones automatizadas."
                    )

                logger.info("Página cargada, buscando artículos de propiedades")
                elements = await page.query_selector_all('article')
                buildings = []

                # También intentamos extraer el JSON de propiedades que a veces se incluye en el HTML
                try:
                    # Evaluar script para extraer datos JSON de la página
                    properties_data = await page.evaluate("""() => {
                        if (window.rdb_properties && Array.isArray(window.rdb_properties)) {
                            return window.rdb_properties;
                        }
                        return null;
                    }""")

                    if properties_data:
                        logger.info(f"Se encontraron {len(properties_data)} propiedades en JSON")
                        for prop in properties_data:
                            try:
                                # Procesamos la imagen principal para asegurarnos de que sea una URL absoluta
                                main_image = self._fix_image_url(prop.get('foto_portada', ''))

                                buildings.append({
                                    "price": prop.get('precio', ''),
                                    "direccion": f"{prop.get('calle', '')}, {prop.get('localidad', '')}",
                                    "image": main_image,
                                    "additional_images": [],  # Array vacío en lugar de procesar imágenes adicionales
                                    "habitaciones": str(prop.get('cant_habitaciones', '')),
                                    "supTotal": str(prop.get('sup_total', '')),
                                    "supCub": str(prop.get('sup_cubierta', '')),
                                    "garage": bool(prop.get('garage', False)),
                                    "banos": str(prop.get('cant_banos', '')),
                                    "url": f"https://inmoup.com.ar{prop.get('url', '')}",
                                    "kid": str(prop.get('id', '')),
                                    "hasgeolocation": "true" if prop.get('lat') and prop.get('lng') else "false",
                                    "latitude": str(prop.get('lat', '')),
                                    "longitude": str(prop.get('lng', '')),
                                    "source": "inmoup"
                                })
                            except Exception as e:
                                logger.error(f"Error procesando propiedad JSON: {str(e)}")
                except Exception as e:
                    logger.error(f"Error extrayendo JSON de propiedades: {str(e)}")

                # Si no pudimos extraer propiedades del JSON, extraer del HTML
                if not buildings:
                    logger.info(f"Se encontraron {len(elements)} propiedades con Playwright")
                    for element in elements:
                        try:
                            price = await element.get_attribute('precio') or ""
                            kid = await element.get_attribute('kid') or ""
                            lat = await element.get_attribute('lat') or ""
                            lng = await element.get_attribute('lng') or ""
                            hasgeolocation = await element.get_attribute('hasgeolocation') or ""
                            sup_total = await element.get_attribute('sup_t') or ""
                            sup_cub = await element.get_attribute('sup_c') or ""
                            habitaciones = await element.get_attribute('ser_1') or ""
                            banos = await element.get_attribute('ser_2') or ""
                            garage = await element.get_attribute('ser_3') or ""

                            direccion_elem = await element.query_selector('div.property-data')
                            direccion = await direccion_elem.inner_text() if direccion_elem else ""
                            direccion = direccion.replace('\n\n', ', ')

                            # Obtener la imagen principal y convertirla a URL absoluta
                            img_elem = await element.query_selector('img')
                            image_rel = await img_elem.get_attribute('src') if img_elem else ""
                            image = self._fix_image_url(image_rel)

                            url_elem = await element.query_selector('a.cont-photo')
                            url = f"https://inmoup.com.ar{await url_elem.get_attribute('href') if url_elem else ''}"

                            buildings.append({
                                "price": price,
                                "direccion": direccion,
                                "image": image,
                                "additional_images": [],  # Array vacío en lugar de procesar imágenes adicionales
                                "habitaciones": habitaciones,
                                "supTotal": sup_total,
                                "supCub": sup_cub,
                                "garage": garage,
                                "banos": banos,
                                "url": url,
                                "kid": kid,
                                "hasgeolocation": hasgeolocation,
                                "latitude": lat,
                                "longitude": lng,
                                "source": "inmoup"
                            })
                        except Exception as e:
                            logger.error(f"Error procesando propiedad: {str(e)}")
                            # Continuamos con la siguiente propiedad si hay un error

                await browser.close()
                return buildings
        except Exception as e:
            logger.error(f"Error general en el scraper de Inmoup con Playwright: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor al procesar datos de inmuebles de Inmoup"
            )

# Función auxiliar para mantener compatibilidad con el código existente
async def get_buildings_inmoup(request=None):
    """
    Función de compatibilidad que instancia InmoupScraper y llama a su método get_buildings
    """
    scraper = InmoupScraper()
    return await scraper.get_buildings(request)
