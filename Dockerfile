# Imagen del servicio de tickets Allianz para EasyPanel.
# Proceso principal: el scheduler autónomo (polling Gmail API + inactividad + retención).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

WORKDIR /app

# Dependencias primero (mejor cache de capas).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código.
COPY . .

# El scheduler corre de forma continua. Todo respeta DRY_RUN: la imagen es segura por
# default (no envía ni purga). Para ir en vivo se setea DRY_RUN=false en EasyPanel.
CMD ["python", "-m", "app.run_scheduler"]
