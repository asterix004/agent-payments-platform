# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# psycopg's C extension, compiled against Debian's libpq. Not psycopg[binary]: that wheel
# vendors its own libpq, OpenSSL and pcre2 from its build distro, which Debian security
# updates never patch (Trivy flags the bundled pcre2).
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libpq-dev && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install -r requirements.txt "psycopg[c]==3.3.6"

FROM python:3.12-slim AS runtime
# Non-root, no shell tools beyond the base image, read-only root filesystem in Kubernetes.
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /venv /venv
WORKDIR /srv
COPY app ./app
ENV PATH=/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8080
# One worker per pod: Prometheus counters live in-process, so multiple workers would give
# inconsistent scrapes. Scale with replicas (HPA) instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
