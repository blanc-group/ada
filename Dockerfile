FROM python:3.11-slim

WORKDIR /app

COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY ada_bridge ./ada_bridge
COPY web ./web

ENV ADA_WEB_HOST=0.0.0.0 \
    ADA_WEB_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "ada_bridge.webapp"]
