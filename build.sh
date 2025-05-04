#!/bin/bash
# Script para instalar dependencias sin navegadores de Playwright
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
export RENDER=true
pip install -r requirements.txt