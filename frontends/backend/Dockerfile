FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY app.py .
EXPOSE 8073
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8073"]
