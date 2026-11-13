FROM python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

WORKDIR /app
COPY --chown=10001:10001 server.py /app/server.py
USER 10001:10001
CMD ["python", "/app/server.py"]
