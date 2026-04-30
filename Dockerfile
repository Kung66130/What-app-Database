FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WA_AGENT_HOST=0.0.0.0
ENV WA_AGENT_PORT=8080
ENV WA_AGENT_DATA_DIR=/app/data

WORKDIR /app

COPY app ./app
COPY main.py README.md PI_SETUP.md ./
COPY sample_data ./sample_data

EXPOSE 8080

CMD ["sh", "-c", "python main.py init-db && python main.py serve"]
