FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 TORCH_HOME=/models OMP_NUM_THREADS=4
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir fastapi "uvicorn[standard]" numpy omegaconf
WORKDIR /app
COPY app.py .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
