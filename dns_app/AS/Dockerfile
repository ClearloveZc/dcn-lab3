FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DB_PATH=/data/records.sqlite3
WORKDIR /app
RUN useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY server.py .
USER 10001:10001
EXPOSE 53533/udp
CMD ["python", "server.py"]
