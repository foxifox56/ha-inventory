FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INVENTORY_DATA_DIR=/data \
    INVENTORY_PORT=8099

WORKDIR /app

COPY backend ./backend
COPY frontend ./frontend

EXPOSE 8099

CMD ["python3", "-m", "backend"]
