# Руководство к файлу: Dockerfile для локального Qdrant и дополнительной цели crawler4ai на порту 11235.
# Qdrant:
# 1) Сборка образа: docker build -t qdrant-local -f Dockerfile .
# 2) Запуск контейнера с сохранением данных: docker run -d --name qdrant -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant-local
# 3) Остановка: docker stop qdrant ; Удаление: docker rm qdrant (данные сохранятся в volume qdrant_storage)
# 4) Порты: 6333 (REST), 6334 (gRPC). Переменные окружения QDRANT__SERVICE__GRPC_PORT и QDRANT__SERVICE__HTTP_PORT можно переопределить при запуске.
# 5) Проверка готовности: curl http://localhost:6333/ready
#
# Crawler4AI (целевой stage crawler4ai):
# 6) Сборка: docker build --target crawler4ai -t crawler4ai-local -f AI/Dockerfile AI/
# 7) Запуск: docker run -d --name crawler4ai -p 11235:11235 crawler4ai-local
# 8) Проверка готовности: curl http://localhost:11235/health
# 9) Краулинг: curl -X POST http://localhost:11235/crawl -H "Content-Type: application/json" -d '{"urls":["https://example.com"]}'
# 10) По умолчанию порт 11235, переопределить можно через -e CRAWL4AI_PORT=XXXX
# ВАЖНО: старый образ unclecode/crawl4ai:basic — только ARM64. Этот stage собирается из python:3.11-slim (amd64).

FROM python:3.11-slim AS crawler4ai

# Системные зависимости для Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    libx11-6 libx11-xcb1 libxcb1 libxext6 libxfixes3 \
    fonts-liberation fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Установка crawl4ai + FastAPI + uvicorn
RUN pip install --no-cache-dir \
    "crawl4ai>=0.4" \
    "fastapi" \
    "uvicorn[standard]"

# Установка браузеров Playwright (только Chromium для экономии места)
RUN crawl4ai-setup || true
RUN playwright install chromium --with-deps || true

# Копируем наш сервер
COPY crawler_server.py /app/crawler_server.py

ENV CRAWL4AI_PORT=11235

EXPOSE 11235

HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
    CMD curl -f http://localhost:11235/health || exit 1

CMD ["uvicorn", "crawler_server:app", "--host", "0.0.0.0", "--port", "11235"]

FROM qdrant/qdrant:latest

# Настройки по умолчанию, можно переопределить при docker run
ENV QDRANT__SERVICE__HTTP_PORT=6333 \
    QDRANT__SERVICE__GRPC_PORT=6334 \
    QDRANT__STORAGE__STORAGE_PATH=/qdrant/storage \
    QDRANT__STORAGE__SNAPSHOTS_PATH=/qdrant/snapshots

VOLUME ["/qdrant/storage", "/qdrant/snapshots"]

EXPOSE 6333 6334

HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD wget --spider -q http://localhost:6333/ready || exit 1

# Используем стандартный entrypoint/command образа qdrant/qdrant
