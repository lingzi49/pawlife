FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pawlife_web.py .

# Fly.io 持久卷挂载点
RUN mkdir -p /data

EXPOSE 8000

CMD ["python", "pawlife_web.py"]
