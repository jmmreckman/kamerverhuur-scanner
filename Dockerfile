FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium + systeemdependencies voor de browsergebaseerde zoekopdrachten
# (zie rotterdam_scanner/browser_scraper.py) - een gewone browser die net als
# een mens de funda-zoekresultatenpagina bezoekt, geen scraping-dienst.
RUN playwright install --with-deps chromium
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["python3", "-m", "scripts.dagelijkse_scan"]
