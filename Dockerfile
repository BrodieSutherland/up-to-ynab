# Build stage
FROM amd64/python:3.9-slim AS build

WORKDIR /build

COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM amd64/python:3.9-slim-buster

EXPOSE 5001

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app
COPY --from=build /root/.local /root/.local
COPY . /app

RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

CMD ["gunicorn", "main:app", "-b", "0.0.0.0:5001", "-w", "4"]
