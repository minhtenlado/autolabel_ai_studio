# CPU container; Linux x86_64/aarch64 subject to official torch wheel support.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AUTOLABEL_HOST=0.0.0.0 AUTOLABEL_PORT=8000 AUTOLABEL_INSECURE_REMOTE=1
COPY requirements.txt requirements-ai.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
  && python -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
  && python -m pip install --no-cache-dir -r requirements-ai.txt
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
COPY launch.py ./launch.py
EXPOSE 8000
# Avoid mapping this unsecured API to an externally exposed/public port.
CMD ["python", "launch.py"]
