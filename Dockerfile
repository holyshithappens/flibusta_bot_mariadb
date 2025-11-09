# Dockerfile
FROM python:3.11-slim-bookworm

## Устанавливаем системные зависимости
#RUN apt-get update && apt-get install -y \
#    curl \
#    wget \
#    chromium \
#    chromium-driver \
#    && rm -rf /var/lib/apt/lists/*

# Создаем пользователя с таким же UID как на хосте
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID botuser && \
    useradd -m -u $UID -g $GID botuser

WORKDIR /app

# Копируем требования сначала для кэширования
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY app/ /app/

# Создаем директории для данных
RUN mkdir -p /app/data /app/logs && \
    chown -R botuser:botuser /app

# Переключаемся на непривилегированного пользователя
USER botuser

# Открываем порт (если нужно)
EXPOSE 8000

# Запускаем бота
CMD ["python", "-u", "main.py"]