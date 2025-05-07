from playwright.async_api import async_playwright
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from .base_scraper import BaseScraper
import os
import time
import asyncio

logger = logging.getLogger(__name__)

class InmoupScraper(BaseScraper):
    def _fix_image_url(self, image_url: str) -> str:
        if not image_url:
            return ""
        if image_url.startswith(('http://', 'https://')):
            return image_url
        return f"https://inmoup.com.ar{image_url}"

    async def get_buildings(self, request: BaseModel) -> List[Dict[str, Any]]:
        start_time = time.time()
        try:
            result = await self._get_buildings_playwright(request)
            elapsed_time = time.time() - start_time
            logger.info(f"Tiempo total de ejecución del scraper: {elapsed_time:.2f} segundos")
            return result
        except Exception as e:
            logger.error(f"Error general en el scraper de Inmoup: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor al procesar datos de inmuebles de Inmoup"
            )

    async def _get_buildings_playwright(self, request: Optional[BaseModel]) -> List[Dict[str, Any]]:
        try:
            async with async_playwright() as p:
                browser_type = p.chromium
                browser_launch_args = {
                    'headless': True,
                    'args': ['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage']
                }

                in_render = os.environ.get('RENDER', 'false').lower() == 'true'
                if in_render:
                    browser_launch_args = {
                        'headless': True,
                        'args': ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-accelerated-2d-canvas', '--disable-gpu']
                    }

                browser = await browser_type.launch(**browser_launch_args)
                page = await browser.new_page()

                # Optimización: Desactivar carga de imágenes para acelerar
                await page.route("**/*.{png,jpg,jpeg}", lambda route: route.abort())

                base_url = "https://inmoup.com.ar/"
                prop_type = "casas-en-alquiler"
                if request and request.property_type and "depart" in request.property_type.lower():
                    prop_type = "departamentos-en-alquiler"

                url = f"{base_url}{prop_type}?favoritos=0&limit=10000&prevEstadoMap=&ordenar=recientes"

                if request and request.cities and len(request.cities) > 0:
                    city_ids = request.cities
                    if isinstance(city_ids, str):
                        formatted_ids = city_ids.replace(',', '%2C')
                    else:
                        formatted_ids = '%2C'.join(str(city_id) for city_id in city_ids)
                    url += f"&localidades={formatted_ids}"
                else:
                    url += "&localidades=1%2C2%2C7%2C19"

                url += "&lastZoom=13&precio%5Bmin%5D=&precio%5Bmax%5D=&moneda=1&sup_cubierta%5Bmin%5D=&sup_cubierta%5Bmax%5D=&sup_total%5Bmin%5D=&sup_total%5Bmax%5D=&recientes=mes"

                logger.info(f"Navegando a URL con Playwright: {url}")

                nav_start_time = time.time()
                try:
                    # Reducir timeout para fallar más rápido si hay problemas
                    await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                except Exception as e:
                    logger.error(f"Error durante la navegación con Playwright: {str(e)}")
                    raise HTTPException(
                        status_code=503,
                        detail="No se pudo acceder a inmoup.com.ar. El sitio podría estar caído o bloqueando peticiones automatizadas."
                    )

                nav_elapsed = time.time() - nav_start_time
                logger.info(f"Navegación completada en {nav_elapsed:.2f} segundos")

                logger.info("Página cargada, buscando artículos de propiedades")
                elements = await page.query_selector_all('article')
                buildings = []

                if elements:
                    logger.info(f"Se encontraron {len(elements)} propiedades con Playwright")

                    # Configuración para obtener imágenes adicionales (ajustable)
                    # Si es true, se intentará obtener imágenes adicionales (más lento)
                    # Si es false, solo se obtendrá la imagen principal (más rápido)
                    get_additional_images = True
                    max_images_per_property = 3  # Limitar número de imágenes para mejorar rendimiento
                    max_click_wait_time = 200  # ms entre clicks (reducido de 500ms)

                    for element in elements:
                        try:
                            # Extracción rápida de atributos
                            attributes = await element.evaluate('''
                                element => {
                                    return {
                                        price: element.getAttribute('precio') || "",
                                        kid: element.getAttribute('kid') || "",
                                        lat: element.getAttribute('lat') || "",
                                        lng: element.getAttribute('lng') || "",
                                        hasgeolocation: element.getAttribute('hasgeolocation') || "",
                                        sup_total: element.getAttribute('sup_t') || "",
                                        sup_cub: element.getAttribute('sup_c') || "",
                                        habitaciones: element.getAttribute('ser_1') || "",
                                        banos: element.getAttribute('ser_2') || "",
                                        garage: element.getAttribute('ser_3') || ""
                                    };
                                }
                            ''')

                            # Extraer texto de dirección
                            direccion_elem = await element.query_selector('div.property-data')
                            direccion = await direccion_elem.inner_text() if direccion_elem else ""
                            direccion = direccion.replace('\n\n', ', ')

                            # Extraer imagen principal
                            img_elem = await element.query_selector('img')
                            image_rel = await img_elem.get_attribute('src') if img_elem else ""
                            image = self._fix_image_url(image_rel)

                            # Extraer URL de la propiedad
                            url_elem = await element.query_selector('a.cont-photo')
                            property_url = await url_elem.get_attribute('href') if url_elem else ''
                            full_url = f"https://inmoup.com.ar{property_url}"

                            additional_images = []

                            # Solo obtener imágenes adicionales si la configuración lo permite
                            if get_additional_images:
                                property_image_container = await element.query_selector('div.property-image')

                                if property_image_container:
                                    await property_image_container.scroll_into_view_if_needed()

                                    cont_photo = await property_image_container.query_selector('a.cont-photo')
                                    if cont_photo:
                                        # Si hay botón "siguiente", hacer algunos clics rápidos
                                        next_btn = await property_image_container.query_selector('div.flechas[style*="right"]')
                                        if next_btn:
                                            # Limitar el número de clics para mejorar rendimiento
                                            for _ in range(min(max_images_per_property, 3)):
                                                try:
                                                    await next_btn.click()
                                                    # Reducir tiempo de espera entre clics
                                                    await page.wait_for_timeout(max_click_wait_time)
                                                except:
                                                    break

                                        # Recoger todas las imágenes de una vez usando evaluateHandle
                                        img_urls = await cont_photo.evaluate('''
                                            elem => Array.from(elem.querySelectorAll('img'))
                                                .map(img => img.getAttribute('src'))
                                                .filter(src => src)
                                        ''')

                                        for src in img_urls:
                                            url_img = self._fix_image_url(src)
                                            if url_img not in additional_images and url_img != image:
                                                additional_images.append(url_img)
                                                if len(additional_images) >= max_images_per_property:
                                                    break

                            buildings.append({
                                "price": attributes["price"],
                                "direccion": direccion,
                                "image": image,
                                "additional_images": additional_images,
                                "habitaciones": attributes["habitaciones"],
                                "supTotal": attributes["sup_total"],
                                "supCub": attributes["sup_cub"],
                                "garage": attributes["garage"],
                                "banos": attributes["banos"],
                                "url": full_url,
                                "kid": attributes["kid"],
                                "hasgeolocation": attributes["hasgeolocation"],
                                "latitude": attributes["lat"],
                                "longitude": attributes["lng"],
                                "source": "inmoup"
                            })
                        except Exception as e:
                            logger.error(f"Error procesando propiedad: {str(e)}")

                await browser.close()
                return buildings
        except Exception as e:
            logger.error(f"Error general en el scraper de Inmoup con Playwright: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Error interno del servidor al procesar datos de inmuebles de Inmoup"
            )

async def get_buildings_inmoup(request=None):
    start_time = time.time()
    scraper = InmoupScraper()
    result = await scraper.get_buildings(request)
    elapsed_time = time.time() - start_time
    logger.info(f"Tiempo total de get_buildings_inmoup: {elapsed_time:.2f} segundos")
    return result
