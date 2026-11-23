FROM python:3.12-alpine

RUN apk add --no-cache \
      tesseract-ocr \
      tesseract-ocr-data-deu \
      tesseract-ocr-data-eng

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    INVENTORY_DATA_DIR=/data \
    INVENTORY_PORT=8099

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend

EXPOSE 8099

CMD ["python3", "-m", "backend"]
