import logging
import json
import asyncio
import aiohttp
import ssl
import certifi
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from .base_scraper import BaseScraper

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MendozaPropScraper(BaseScraper):
    """
    Scraper específico para el sitio MendozaProp que utiliza su API REST
    """

    def __init__(self):
        self.geocode_cache = {}  # Caché de geocodificación para evitar solicitudes repetidas

    async def get_buildings(self, request: BaseModel) -> List[Dict[str, Any]]:
        """
        Implementación optimizada del método para obtener propiedades de MendozaProp mediante su API

        Args:
            request: Objeto BuildingSearchRequest con los parámetros de búsqueda

        Returns:
            Lista de propiedades encontradas
        """
        try:
            buildings = []
            offset = 0
            limit = 50  # Aumentamos el límite para reducir número de páginas
            more_properties = True
            max_pages = 5  # Reducimos a 5 páginas (250 propiedades) para mejorar rendimiento
            page_count = 0

            # Determinar tipo de operación (1 = alquiler)
            operation_type = "1"

            # Tipos de propiedades (por defecto todos los tipos para alquiler)
            property_type = "40%2C3%2C45%2C46%2C5%2C1119%2C1154%2C1118%2C1117%2C1144%2C1145%2C4%2C7%2C1107%2C1106%2C1108%2C1140"

            if request and request.property_type:
                # Ajustamos el tipo de propiedad si está especificado
                if "depart" in request.property_type.lower():
                    # Filtrar solo departamentos
                    property_type = "3"
                elif "casa" in request.property_type.lower():
                    # Filtrar solo casas
                    property_type = "1"

            # Determinar regiones basadas en las ciudades proporcionadas
            region = "guaymallen%2Cmendoza%2Cgodoycruz"  # Por defecto

            if request and request.cities and len(request.cities) > 0:
                # Convertir ciudades a formato de región esperado por MendozaProp
                city_map = {
                    "mendoza": "mendoza",
                    "godoycruz": "godoycruz",
                    "guaymallen": "guaymallen",
                    "lasheras": "lasheras",
                    "lujandecuyo": "lujandecuyo",
                    "maipu": "maipu",
                    "sanrafael": "sanrafael",
                    "sanmartin": "sanmartin",
                    "tunuyan": "tunuyan",
                    "junin": "junin",
                    "lavalle": "lavalle",
                    "tupungato": "tupungato",
                    "sancarlos": "sancarlos",
                    "generalalvear": "generalalvear",
                    "santarosa": "santarosa",
                    "rivadavia": "rivadavia",
                    "malargue": "malargue",
                    "lapaz": "lapaz"
                }

                regions = []
                for city in request.cities:
                    city_lower = city.lower()
                    if city_lower in city_map:
                        regions.append(city_map[city_lower])
                    else:
                        # Si no encontramos la conversión, usamos el valor tal cual
                        regions.append(city_lower)

                if regions:
                    region = "%2C".join(regions)

            total_properties = 0
            properties_data = []

            # Configurar SSL para macOS
            # Utilizamos los certificados del sistema operativo mediante certifi
            ssl_context = ssl.create_default_context(cafile=certifi.where())

            # Usamos aiohttp.ClientSession para mejorar la eficiencia de las conexiones HTTP
            # Configuramos el contexto SSL personalizado
            conn = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60), connector=conn) as session:
                # Loop para obtener todas las propiedades con paginación
                while more_properties and page_count < max_pages:
                    page_count += 1
                    # Construir URL de API con los parámetros adecuados y solicitar datos con geolocalización
                    api_url = f"https://www.mendozaprop.com/api/properties?limit={limit}&offset={offset}&isMap=true&operationType={operation_type}&propertyType={property_type}&region={region}"

                    logger.info(f"Consultando API MendozaProp (Página {page_count}): {api_url}")

                    try:
                        async with session.get(api_url, timeout=15) as response:
                            if response.status != 200:
                                logger.error(f"Error en la API de MendozaProp: {response.status} - {await response.text()}")
                                raise HTTPException(
                                    status_code=503,
                                    detail=f"No se pudo acceder a la API de MendozaProp. Código de estado: {response.status}"
                                )

                            data = await response.json()
                            logger.info(f"Recibida respuesta de la API de MendozaProp (página {page_count})")
                    except asyncio.TimeoutError:
                        logger.error(f"Timeout al consultar la API de MendozaProp para la página {page_count}")
                        break
                    except Exception as e:
                        logger.error(f"Error al conectar con MendozaProp: {str(e)}")
                        # En caso de error, probamos con verificación SSL deshabilitada (solo para desarrollo)
                        try:
                            logger.warning("Reintentando con verificación SSL deshabilitada (solo para desarrollo)")
                            # Crear un conector sin verificación SSL (para desarrollo)
                            unsafe_connector = aiohttp.TCPConnector(ssl=False)
                            async with aiohttp.ClientSession(connector=unsafe_connector) as unsafe_session:
                                async with unsafe_session.get(api_url, timeout=15) as response:
                                    if response.status != 200:
                                        logger.error(f"Error en la API de MendozaProp: {response.status} - {await response.text()}")
                                        raise HTTPException(
                                            status_code=503,
                                            detail=f"No se pudo acceder a la API de MendozaProp. Código de estado: {response.status}"
                                        )

                                    data = await response.json()
                                    logger.info(f"Recibida respuesta de la API de MendozaProp (página {page_count}) con verificación SSL deshabilitada")
                        except Exception as inner_e:
                            logger.error(f"Error persistente al conectar con MendozaProp incluso sin verificación SSL: {str(inner_e)}")
                            raise HTTPException(
                                status_code=503,
                                detail=f"No se pudo conectar con MendozaProp: {str(inner_e)}"
                            )

                    # La respuesta es directamente una lista de propiedades
                    properties = data if isinstance(data, list) else []

                    if not properties:
                        logger.info("No se encontraron más propiedades")
                        more_properties = False
                        break

                    logger.info(f"Se encontraron {len(properties)} propiedades en la página {page_count}")
                    properties_data.extend(properties)

                    # Incrementar offset para la siguiente página
                    offset += len(properties)

                    # Si recibimos menos propiedades que el límite, hemos llegado al final
                    if len(properties) < limit:
                        logger.info(f"Recibidas menos propiedades ({len(properties)}) que el límite ({limit}). No hay más páginas.")
                        more_properties = False

                if page_count >= max_pages:
                    logger.info(f"Se alcanzó el límite máximo de {max_pages} páginas")

                # Procesar todas las propiedades en paralelo
                # Creamos tareas asíncronas para procesar cada propiedad
                tasks = []
                for prop in properties_data:
                    tasks.append(self._process_property(prop, session))

                # Ejecutamos todas las tareas en paralelo y esperamos los resultados
                processed_properties = await asyncio.gather(*tasks, return_exceptions=True)

                # Filtramos los resultados exitosos (no excepciones)
                for result in processed_properties:
                    if isinstance(result, dict):  # Sólo añadir resultados válidos (no excepciones)
                        buildings.append(result)
                        total_properties += 1

            logger.info(f"Total: Se procesaron {total_properties} propiedades en MendozaProp entre {page_count} páginas")
            return buildings

        except Exception as e:
            logger.error(f"Error general en el scraper de MendozaProp: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error interno del servidor al procesar datos de inmuebles de MendozaProp: {str(e)}"
            )

    async def _process_property(self, prop: Dict, session: aiohttp.ClientSession) -> Dict[str, Any]:
        """
        Procesa una propiedad individual de forma asíncrona

        Args:
            prop: Datos de la propiedad
            session: Sesión HTTP asincrona

        Returns:
            Datos procesados de la propiedad
        """
        try:
            property_id = prop.get("id", "")

            # Debug: Registrar la estructura de la propiedad para depuración
            logger.debug(f"Procesando propiedad ID: {property_id}")

            # Extraer datos de coordenadas de diferentes fuentes posibles
            latitude = self._extract_value(prop, ["latitude", "google_lat"])
            longitude = self._extract_value(prop, ["longitude", "google_lng"])

            # Buscar en campos anidados
            if not latitude or not longitude:
                # Revisar "map" si existe
                map_data = prop.get("map", {})
                if isinstance(map_data, dict):
                    latitude = latitude or map_data.get("latitude", "")
                    longitude = longitude or map_data.get("longitude", "")

                # Revisar "coords" si existe
                coords = prop.get("coords", {})
                if isinstance(coords, dict):
                    latitude = latitude or coords.get("lat", "")
                    longitude = longitude or coords.get("lng", "")

                # Revisar "location" si existe
                location = prop.get("location", {})
                if isinstance(location, dict):
                    latitude = latitude or location.get("latitude", location.get("lat", ""))
                    longitude = longitude or location.get("longitude", location.get("lng", ""))

            # Si no hay coordenadas y tenemos una dirección, intentamos geocodificar (con caché)
            direccion = prop.get("address", "")
            if direccion and (not latitude or not longitude):
                # Primero verificamos si ya tenemos esta dirección en caché
                if direccion in self.geocode_cache:
                    latitude, longitude = self.geocode_cache[direccion]
                    logger.info(f"Usando coordenadas en caché para: {direccion}")
                else:
                    # Utilizamos geocodificación solo si es necesario
                    latitude, longitude = await self._geocode_address(direccion, session)
                    if latitude and longitude:
                        # Guardar en caché para futuros usos
                        self.geocode_cache[direccion] = (latitude, longitude)

            # En MendozaProp, las imágenes pueden venir en diferentes formatos
            # Vamos a probar varias posibilidades para obtener las imágenes
            main_image = ""
            additional_images = []

            # Estrategia 1: Field 'images' como lista directa de URLs
            all_images = prop.get("images", [])

            # Estrategia 2: Field 'photos' o 'gallery' que puede contener las imágenes
            if not all_images:
                all_images = prop.get("photos", prop.get("gallery", []))

            # Estrategia 3: Field 'media' que podría contener las imágenes
            if not all_images:
                media = prop.get("media", {})
                if isinstance(media, dict):
                    all_images = media.get("images", [])

            # Estrategia 4: Field 'image' o 'photo' singular que podría ser la imagen principal
            main_image_direct = prop.get("image", prop.get("photo", ""))
            if main_image_direct:
                main_image = main_image_direct

            # Procesar el array de imágenes según su formato
            if all_images:
                # Convertir a lista si no lo es
                if not isinstance(all_images, list):
                    all_images = [all_images]

                # Procesar las imágenes según su tipo
                processed_images = []
                for img in all_images:
                    # Caso 1: La imagen es directamente una URL (string)
                    if isinstance(img, str):
                        processed_images.append(img)
                    # Caso 2: La imagen es un objeto con una URL en 'url', 'src', o 'path'
                    elif isinstance(img, dict):
                        img_url = img.get("url", img.get("src", img.get("path", "")))
                        if img_url:
                            processed_images.append(img_url)

                # Si encontramos imágenes procesadas, usarlas
                if processed_images:
                    # Primera imagen como principal (si no tenemos ya una imagen principal)
                    if not main_image and processed_images:
                        main_image = processed_images[0]

                    # Resto como adicionales (limitamos a 10 para evitar sobrecarga)
                    # Si ya teníamos una imagen principal directa, incluimos todas las procesadas como adicionales
                    if main_image_direct:
                        additional_images = processed_images[:10]
                    else:
                        additional_images = processed_images[1:11]  # Tomamos del segundo al décimo elemento

            # Si main_image es un objeto o un array, intentamos extraer la URL
            if isinstance(main_image, dict):
                main_image = main_image.get("url", main_image.get("src", main_image.get("path", "")))
            elif isinstance(main_image, list) and len(main_image) > 0:
                main_image = main_image[0] if isinstance(main_image[0], str) else ""

            # Asegurar que additional_images sea una lista de strings
            if not isinstance(additional_images, list):
                additional_images = []

            # Asegurar que las URLs de las imágenes sean absolutas
            if main_image and not main_image.startswith(('http://', 'https://')):
                main_image = f"https://www.mendozaprop.com{main_image if main_image.startswith('/') else '/' + main_image}"

            additional_images = [
                (f"https://www.mendozaprop.com{img if img.startswith('/') else '/' + img}"
                if not img.startswith(('http://', 'https://')) else img)
                for img in additional_images if img
            ]

            # Registrar info de depuración sobre las imágenes
            logger.debug(f"Propiedad {property_id} - Imagen principal: {main_image}")
            logger.debug(f"Propiedad {property_id} - Imágenes adicionales: {len(additional_images)}")

            # Construir objeto de propiedad con validaciones
            property_data = {
                "id": str(property_id),
                "price": f"{prop.get('price', '')} {prop.get('currency_id', '') == 1 and 'USD' or 'ARS'}",
                "direccion": direccion,
                "image": main_image,
                "additional_images": additional_images,
                "habitaciones": str(prop.get("bedrooms", "")),
                "supTotal": str(prop.get("m2", "")),
                "supCub": str(prop.get("m2_covered", "")),
                "banos": str(prop.get("bathrooms", "")),
                "garage": bool(prop.get("parking", 0) > 0),
                "url": f"https://www.mendozaprop.com/alquiler/{property_id}",
                "latitude": str(latitude),
                "longitude": str(longitude),
                "hasgeolocation": bool(latitude and longitude),
                "description": str(prop.get("description", "")),
                "source": "mendozaprop"
            }

            return property_data

        except Exception as e:
            logger.error(f"Error procesando propiedad {prop.get('id', '')}: {str(e)}")
            raise e

    def _extract_value(self, data: Dict, keys: List[str]) -> str:
        """
        Extrae un valor de un diccionario probando múltiples claves

        Args:
            data: Diccionario de datos
            keys: Lista de claves a probar

        Returns:
            El primer valor encontrado o cadena vacía
        """
        for key in keys:
            value = data.get(key, "")
            if value:
                return value
        return ""

    async def _geocode_address(self, address: str, session: aiohttp.ClientSession) -> tuple:
        """
        Geocodifica una dirección usando el servicio de Nominatim

        Args:
            address: Dirección a geocodificar
            session: Sesión HTTP asincrona

        Returns:
            Tupla (latitud, longitud) o ("", "")
        """
        try:
            # Preparar dirección para búsqueda (añadiendo Mendoza Argentina)
            search_address = f"{address}, Mendoza, Argentina"

            # Usar la API de geocodificación de nominatim (OpenStreetMap)
            geocode_url = f"https://nominatim.openstreetmap.org/search?q={search_address}&format=json&limit=1"
            headers = {
                'User-Agent': 'MendozaPropScraper/1.0'  # Necesario para usar la API de Nominatim
            }

            # Hacemos solicitud con timeout
            async with session.get(geocode_url, headers=headers, timeout=5) as response:
                if response.status == 200:
                    geocode_data = await response.json()
                    if geocode_data and len(geocode_data) > 0:
                        # Extraer coordenadas
                        location_data = geocode_data[0]
                        return location_data.get("lat", ""), location_data.get("lon", "")

            return "", ""
        except Exception as e:
            logger.warning(f"Error en geocodificación para {address}: {str(e)}")
            return "", ""

# Función auxiliar para mantener compatibilidad con el código existente
async def get_buildings_mendozaprop(request=None):
    """
    Función de compatibilidad que instancia MendozaPropScraper y llama a su método get_buildings
    """
    scraper = MendozaPropScraper()
    return await scraper.get_buildings(request)
