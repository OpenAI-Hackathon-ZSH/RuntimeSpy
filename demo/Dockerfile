FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY demo/pyproject.toml ./demo/pyproject.toml
COPY demo/src ./demo/src
RUN python -m pip install --no-cache-dir ./demo "gunicorn>=23,<24"

COPY demo/.runtimespy.toml demo/app.py ./demo/

WORKDIR /app/demo

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "60", "app:app"]
