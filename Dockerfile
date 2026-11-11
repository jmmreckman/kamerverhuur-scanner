FROM python:3.12-slim

WORKDIR /app

# rclone: voor het automatisch wegschrijven van getekende contracten naar
# Drive (zie kamerverhuur_scanner/drive_sync.py) - gebruikt in plaats van het
# Google service account, dat zelf 0 GB Drive-opslag heeft.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip \
    && curl https://rclone.org/install.sh | bash \
    && apt-get purge -y curl unzip && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# rclone's config (incl. de Drive-inlogtoken, zie hierboven) moet in de
# blijvend gekoppelde data-map staan (STATE_DIR=/app/data, gekoppeld aan een
# volume in docker-compose.yml) - anders staat 'ie alleen in de schrijfbare
# laag van de container, en verdwijnt hij zodra de container een keer
# opnieuw wordt opgebouwd (bv. bij elke herdeploy).
ENV RCLONE_CONFIG=/app/data/rclone.conf

EXPOSE 8000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120", "webapp.app:create_app()"]
