FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
WORKDIR /app/backend
COPY backend/requirements.lock /app/backend/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock \
    && playwright install --with-deps chromium
COPY backend/pyproject.toml backend/alembic.ini /app/backend/
COPY backend/src /app/backend/src
COPY backend/alembic /app/backend/alembic
RUN pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home agrm \
    && chown -R agrm:agrm /app
USER agrm
EXPOSE 8000
CMD ["agrm-api"]
