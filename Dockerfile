FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY configs ./configs
COPY data ./data
COPY dashboard ./dashboard
COPY case_studies ./case_studies

RUN python -m pip install --upgrade pip && \
    python -m pip install .

CMD ["energy-hub", "--help"]
