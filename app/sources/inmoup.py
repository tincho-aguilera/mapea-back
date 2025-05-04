from playwright.async_api import async_playwright
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
from .base_scraper import BaseScraper
import httpx
import asyncio
import json
import re
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
            # Primero intentamos usar httpx (método más liviano)
            buildings = await self._get_buildings_httpx(request)
            
            # Si no hay imágenes reales, recurrimos a Playwright como fallback
            missing_images = all(
                "/bundles/inmoup/images/v11.03/empty-photo-box.jpg" in building.get("image", "")
                for building in buildings
            )
            
            if missing_images and buildings:
                logger.warning("Todas las imágenes son placeholders, intentando con Playwright")
                try:
                    # Intentamos obtener solo las imágenes con Playwright
                    return await self._enhance_with_playwright_images(buildings, request)
                except Exception as e:
                    logger.warning(f"Error al mejorar imágenes con Playwright: {str(e)}")
                    # Retornamos los resultados de httpx aunque tengan imágenes placeholder
                    return buildings
            
            return buildings
            
        except Exception as e:
            logger.warning(f"Error con httpx, intentando con Playwright completo: {str(e)}")
            try:
                # Si falla completamente httpx, intentamos con Playwright como respaldo
                return await self._get_buildings_playwright(request)
            except Exception as e:
                logger.error(f"Error general en el scraper de Inmoup: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="Error interno del servidor al procesar datos de inmuebles de Inmoup"
                )

    async def _enhance_with_playwright_images(self, buildings: List[Dict[str, Any]], request: BaseModel) -> List[Dict[str, Any]]:
        """
        Mejora los resultados de httpx con imágenes obtenidas mediante Playwright
        """
        # Si no hay edificios para mejorar, devolver la lista vacía
        if not buildings:
            return []
            
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

        logger.info(f"Mejorando imágenes con Playwright para URL: {url}")
        
        try:
            async with async_playwright() as p:
                # Usar opciones más robustas para entornos de producción
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage']
                )
                
                page = await browser.new_page()
                
                try:
                    await page.goto(
                        url,
                        timeout=60000,  # Incrementar a 60 segundos
                        wait_until="domcontentloaded"  # Cambiar el evento de espera
                    )
                except Exception as e:
                    logger.error(f"Error durante la navegación con Playwright para imágenes: {str(e)}")
                    await browser.close()
                    return buildings  # Devolver los edificios sin mejorar las imágenes
                
                logger.info("Buscando imágenes con Playwright")
                elements = await page.query_selector_all('article')
                
                # Crear un mapa de kid -> imagen para actualizar rápidamente los edificios
                image_map = {}
                for element in elements:
                    try:
                        kid = await element.get_attribute('kid') or ""
                        
                        # Obtener la imagen principal
                        img_elem = await element.query_selector('img')
                        image_rel = await img_elem.get_attribute('src') if img_elem else ""
                        
                        # Si no es un placeholder, guardar la imagen
                        if image_rel and "empty-photo-box.jpg" not in image_rel:
                            image = self._fix_image_url(image_rel)
                            image_map[kid] = image
                        
                        # Obtener imágenes adicionales
                        additional_images = []
                        image_elems = await element.query_selector_all('.fotos-ficha')
                        for img_elem in image_elems:
                            img_url = await img_elem.get_attribute('src')
                            if img_url and "empty-photo-box.jpg" not in img_url:
                                fixed_url = self._fix_image_url(img_url)
                                additional_images.append(fixed_url)
                        
                        if not additional_images:
                            image_elems = await element.query_selector_all('[itemscope="photo"]')
                            for img_elem in image_elems:
                                img_url = await img_elem.get_attribute('src')
                                if img_url and "empty-photo-box.jpg" not in img_url:
                                    fixed_url = self._fix_image_url(img_url)
                                    additional_images.append(fixed_url)
                        
                        if additional_images:
                            if kid in image_map:
                                image_map[kid] = {
                                    'main': image_map[kid],
                                    'additional': additional_images
                                }
                            else:
                                image_map[kid] = {
                                    'main': self._fix_image_url(image_rel),
                                    'additional': additional_images
                                }
                    except Exception as e:
                        logger.error(f"Error procesando imágenes para propiedad {kid}: {str(e)}")
                
                await browser.close()
                
                # Actualizar los edificios con las imágenes reales
                enhanced_buildings = []
                for building in buildings:
                    kid = building.get('kid', '')
                    if kid in image_map:
                        if isinstance(image_map[kid], dict):
                            building['image'] = image_map[kid]['main']
                            building['additional_images'] = image_map[kid]['additional']
                        else:
                            building['image'] = image_map[kid]
                    enhanced_buildings.append(building)
                
                logger.info(f"Se mejoraron las imágenes de {len(image_map)} propiedades")
                return enhanced_buildings
                
        except Exception as e:
            logger.error(f"Error al mejorar imágenes con Playwright: {str(e)}")
            return buildings  # Devolver los edificios sin mejorar las imágenes

    async def _get_buildings_httpx(self, request: Optional[BaseModel]) -> List[Dict[str, Any]]:
        """
        Obtiene propiedades usando httpx (método liviano sin navegador)
        """
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

        logger.info(f"Haciendo solicitud HTTP a: {url}")
        
        # Usar httpx para hacer la solicitud
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)
            
            if response.status_code != 200:
                logger.error(f"Error en la solicitud HTTP: {response.status_code}")
                raise HTTPException(
                    status_code=503,
                    detail=f"No se pudo acceder a inmoup.com.ar. Código de estado: {response.status_code}"
                )
            
            # Extraer los datos de propiedades usando BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            articles = soup.find_all('article')
            
            logger.info(f"Se encontraron {len(articles)} propiedades con httpx")
            
            # También intentamos extraer el JSON de propiedades que a veces se incluye en el HTML
            buildings = []
            
            # Buscar scripts en la página que puedan contener datos JSON
            scripts = soup.find_all('script')
            properties_data = None
            
            for script in scripts:
                if script.string and 'window.rdb_properties = ' in script.string:
                    # Extraer el JSON de propiedades
                    json_str = re.search(r'window\.rdb_properties = (\[.*?\]);', script.string, re.DOTALL)
                    if json_str:
                        try:
                            properties_data = json.loads(json_str.group(1))
                            break
                        except json.JSONDecodeError:
                            pass
            
            # Si encontramos datos JSON, los procesamos
            if properties_data:
                for prop in properties_data:
                    try:
                        # Procesamos la imagen principal para asegurarnos de que sea una URL absoluta
                        main_image = self._fix_image_url(prop.get('foto_portada', ''))
                        
                        # Procesamos las imágenes adicionales
                        additional_imgs = []
                        for img in prop.get('fotos', []):
                            fixed_img = self._fix_image_url(img)
                            if fixed_img:
                                additional_imgs.append(fixed_img)
                        
                        buildings.append({
                            "price": prop.get('precio', ''),
                            "direccion": f"{prop.get('calle', '')}, {prop.get('localidad', '')}",
                            "image": main_image,
                            "additional_images": additional_imgs,
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
            
            # Si no se pudieron extraer propiedades del JSON, extraerlas del HTML
            if not buildings:
                for article in articles:
                    try:
                        # Extraer datos de los artículos HTML
                        price = article.get('precio', '')
                        kid = article.get('kid', '')
                        lat = article.get('lat', '')
                        lng = article.get('lng', '')
                        hasgeolocation = article.get('hasgeolocation', '')
                        sup_total = article.get('sup_t', '')
                        sup_cub = article.get('sup_c', '')
                        habitaciones = article.get('ser_1', '')
                        banos = article.get('ser_2', '')
                        garage = article.get('ser_3', '')
                        
                        # Extraer dirección
                        direccion_elem = article.select_one('div.property-data')
                        direccion = direccion_elem.text.strip().replace('\n\n', ', ') if direccion_elem else ""
                        
                        # Obtener la imagen principal y convertirla a URL absoluta
                        img_elem = article.select_one('img')
                        image_rel = img_elem.get('src', '') if img_elem else ""
                        image = self._fix_image_url(image_rel)
                        
                        # Obtener URL de la propiedad
                        url_elem = article.select_one('a.cont-photo')
                        prop_url = f"https://inmoup.com.ar{url_elem.get('href', '')}" if url_elem else ""
                        
                        buildings.append({
                            "price": price,
                            "direccion": direccion,
                            "image": image,
                            "additional_images": [],
                            "habitaciones": habitaciones,
                            "supTotal": sup_total,
                            "supCub": sup_cub,
                            "garage": garage,
                            "banos": banos,
                            "url": prop_url,
                            "kid": kid,
                            "hasgeolocation": hasgeolocation,
                            "latitude": lat,
                            "longitude": lng,
                            "source": "inmoup"
                        })
                    except Exception as e:
                        logger.error(f"Error procesando propiedad HTML: {str(e)}")
            
            return buildings

    async def _get_buildings_playwright(self, request: Optional[BaseModel]) -> List[Dict[str, Any]]:
        """
        Implementación del método para obtener propiedades de Inmoup usando Playwright como fallback
        """
        try:
            async with async_playwright() as p:
                # Usar opciones más robustas para entornos de producción
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage']
                )
                
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
                    await page.goto(
                        url,
                        timeout=60000,  # Incrementar a 60 segundos
                        wait_until="domcontentloaded"  # Cambiar el evento de espera
                    )
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

                        # Obtener todas las imágenes adicionales (las que se ven en gris en la imagen)
                        additional_images = []
                        image_elems = await element.query_selector_all('.fotos-ficha')
                        for img_elem in image_elems:
                            img_url = await img_elem.get_attribute('src')
                            if img_url:
                                # Convertir a URL absoluta
                                fixed_url = self._fix_image_url(img_url)
                                if fixed_url not in additional_images:
                                    additional_images.append(fixed_url)

                        # Si no se encuentran con 'src', intentar obtener las URLs de las imágenes desde el atributo itemscope
                        if not additional_images:
                            image_elems = await element.query_selector_all('[itemscope="photo"]')
                            for img_elem in image_elems:
                                img_url = await img_elem.get_attribute('src')
                                if img_url:
                                    # Convertir a URL absoluta
                                    fixed_url = self._fix_image_url(img_url)
                                    if fixed_url not in additional_images:
                                        additional_images.append(fixed_url)

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
