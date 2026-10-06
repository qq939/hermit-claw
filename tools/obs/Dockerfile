FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

RUN mkdir -p obs obs/.chunks

# obs 图床固定宿主机端口 18000（18xxx 工具类端口段），容器内统一 8082
ENV PORT=8082

EXPOSE 8082

CMD ["python", "server.py"]
