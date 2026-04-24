FROM python:3.11-slim

WORKDIR /app

# Шрифты с поддержкой кириллицы (для Pillow standings image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код
COPY . .

CMD ["python", "main.py"]
