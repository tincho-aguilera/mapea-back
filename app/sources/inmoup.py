from playwright.async_api import async_playwright
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from .base_scraper import BaseScraper

# Configurar logging
logger = logging.getLogger(__name__)

class InmoupScraper(BaseScraper):
    """
    Scraper específico para el sitio Inmoup
    """

    async def get_buildings(self, request: BaseModel) -> List[Dict[str, Any]]:
        """
        Implementación del método para obtener propiedades de Inmoup

        Args:
            request: Objeto BuildingSearchRequest con los parámetros de búsqueda

        Returns:
            Lista de propiedades encontradas
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
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

                logger.info(f"Navegando a URL: {url}")

                # Aumentar el timeout a 60 segundos y agregar logs para debug
                logger.info("Iniciando navegación a inmoup.com.ar")
                try:
                    await page.goto(
                        url,
                        timeout=60000,  # Incrementar a 60 segundos
                        wait_until="domcontentloaded"  # Cambiar el evento de espera
                    )
                except Exception as e:
                    logger.error(f"Error durante la navegación: {str(e)}")
                    # Mostrar un error más amigable al usuario
                    raise HTTPException(
                        status_code=503,
                        detail="No se pudo acceder a inmoup.com.ar. El sitio podría estar caído o bloqueando peticiones automatizadas."
                    )

                logger.info("Página cargada, buscando artículos de propiedades")
                elements = await page.query_selector_all('article')
                buildings = []

                logger.info(f"Se encontraron {len(elements)} propiedades")
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

                        # Obtener la imagen principal
                        img_elem = await element.query_selector('img')
                        image = await img_elem.get_attribute('src') if img_elem else ""

                        # Obtener todas las imágenes adicionales (las que se ven en gris en la imagen)
                        additional_images = []
                        image_elems = await element.query_selector_all('.fotos-ficha')
                        for img_elem in image_elems:
                            img_url = await img_elem.get_attribute('src')
                            if img_url and img_url not in additional_images:
                                additional_images.append(img_url)

                        # Si no se encuentran con 'src', intentar obtener las URLs de las imágenes desde el atributo itemscope
                        if not additional_images:
                            image_elems = await element.query_selector_all('[itemscope="photo"]')
                            for img_elem in image_elems:
                                img_url = await img_elem.get_attribute('src')
                                if img_url and img_url not in additional_images:
                                    additional_images.append(img_url)

                        url_elem = await element.query_selector('a.cont-photo')
                        url = f"https://inmoup.com.ar{await url_elem.get_attribute('href') if url_elem else ''}"

                        buildings.append({
                            "price": price,
                            "direccion": direccion,
                            "image": image,
                            "additional_images": additional_images,
                            "habitaciones": habitaciones,
                            "supTotal": sup_total,
                            "supCub": sup_cub,
                            "garage": garage,
                            "banos": banos,
                            "url": url,
                            "kid": kid,
                            "hasgeolocation": hasgeolocation,
                            "latitude": lat,
                            "longitude": lng
                        })
                    except Exception as e:
                        logger.error(f"Error procesando propiedad: {str(e)}")
                        # Continuamos con la siguiente propiedad si hay un error

                await browser.close()
                return buildings
        except Exception as e:
            logger.error(f"Error general en el scraper de Inmoup: {str(e)}")
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
