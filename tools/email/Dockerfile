FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY email_sender.py .
COPY email_receiver.py .
COPY asset/ asset/

RUN mkdir -p /var/log && chmod 777 /var/log

ENV PORT=5030

EXPOSE 5030

CMD ["python", "-u", "app.py"]
