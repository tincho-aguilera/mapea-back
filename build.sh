#!/bin/bash
# Script para instalar Playwright solo con Chromium en Render.com
pip install -r requirements.txt
# Instalar Playwright con solo el navegador Chromium
npx playwright install --with-deps chromium