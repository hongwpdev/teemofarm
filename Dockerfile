FROM python:3.12-slim
ENV TZ=Asia/Seoul PYTHONUNBUFFERED=1 DB_PATH=/data/stove.db RELOAD=0
WORKDIR /app
COPY app.py .
COPY tracker ./tracker
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["python", "app.py"]
