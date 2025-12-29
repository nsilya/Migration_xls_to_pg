FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rpa_migration_bot.py .


CMD ["python", "rpa_migration_bot.py"]