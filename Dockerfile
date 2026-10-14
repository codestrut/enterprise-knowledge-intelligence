FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.docker.txt .

RUN pip install --no-cache-dir -r requirements.docker.txt

COPY src ./src
COPY pytest.ini .

# Uploaded documents and the manifest are runtime data. They are never baked
# into the image; mount a volume to keep them, for example:
#   docker run -v ekip-data:/app/data -p 8000:8000 <image>
RUN mkdir -p /app/data/uploads

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
