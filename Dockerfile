# OTC Signal Bot – production image
FROM python:3.12-slim

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
RUN python -c "import BinaryOptionsToolsV2; print('BOTV2 OK')"

COPY . .

# Non-root user
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

ENV PYTHONUNBUFFERED=1
ENV ENV=production
ENV DEMO_MODE=true

# Default: run the Telegram bot
CMD ["python", "-m", "src.bot.main"]
