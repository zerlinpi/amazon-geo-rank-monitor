FROM python:3.12-slim

WORKDIR /app
COPY backend /app/backend
WORKDIR /app/backend
RUN pip install --no-cache-dir . \
    && playwright install --with-deps chromium

EXPOSE 8000
CMD ["agrm-api"]
