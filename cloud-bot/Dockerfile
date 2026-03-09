FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY scripts/feishu_bot_server.py /app/scripts/feishu_bot_server.py

EXPOSE 9000

CMD ["python", "/app/scripts/feishu_bot_server.py"]
