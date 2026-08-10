FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /opt/program

COPY infra/model-a-container/requirements-container.txt ./
RUN pip install --no-cache-dir -r requirements-container.txt

COPY infra/model-a-container/app/ ./
COPY data/csv/inventory.csv ./data/inventory.csv

EXPOSE 8080
ENTRYPOINT ["python", "serve.py"]
