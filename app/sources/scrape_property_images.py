import asyncio
import time
from playwright.async_api import async_playwright

async def scrape_property_images(url: str) -> list:
    start_time = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")

        # Esperar el contenedor principal de imágenes
        await page.wait_for_selector("div.flex-viewport ul.slides")

        # Seleccionar todas las imágenes dentro del carrusel
        img_elements = await page.query_selector_all("div.flex-viewport ul.slides li img[itemprop='image']")

        # Extraer URLs
        image_urls = []
        for img in img_elements:
            src = await img.get_attribute("src")
            if src:
                image_urls.append(src)

        await browser.close()

        elapsed_time = time.time() - start_time
        print(f"Tiempo de ejecución: {elapsed_time:.2f} segundos")

        return image_urls

# Solo se ejecuta si se llama directamente al script
if __name__ == "__main__":
    url = "https://inmoup.com.ar/10325-inmobiliaria-perez-elustondo/inmuebles/295/ficha/casa-en-alquiler-en-saens-pena-1144-godoy-cruz"
    images = asyncio.run(scrape_property_images(url))
    print("Imágenes encontradas:")
    for img in images:
        print(img)
