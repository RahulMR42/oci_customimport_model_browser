# syntax=docker/dockerfile:1

FROM container-registry.oracle.com/os/oraclelinux:9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

RUN microdnf install -y python3.11 shadow-utils \
    && useradd -r -u 1000 odosvc \
    && microdnf clean all

# Keep the dependency install separate so it is cached when only application
# source files change. requirements.txt currently contains no third-party deps.
COPY requirements.txt ./
RUN python3.11 -m ensurepip --upgrade \
    && python3.11 -m pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY static ./static

RUN chown -R odosvc:odosvc /app

USER odosvc

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3.11 -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/api/health', timeout=3)" || exit 1

CMD ["python3.11", "app.py"]
