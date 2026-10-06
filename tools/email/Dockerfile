FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY email_sender.py .
COPY email_receiver.py .

RUN mkdir -p /var/log && chmod 777 /var/log

# email 邮件固定宿主机端口 18001（18xxx 工具类端口段），容器内统一 8082
ENV PORT=8082

EXPOSE 8082

CMD ["python", "-u", "app.py"]
