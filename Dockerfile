FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-live.txt ./
RUN pip install --no-cache-dir -r requirements-live.txt
COPY live_service.py short_render.py live-public.pem ./
COPY third-party/neonclipping/ third-party/neonclipping/
RUN useradd --create-home clipper && chown -R clipper:clipper /app
USER clipper
EXPOSE 10000
CMD ["python", "live_service.py"]
