FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY service/frontend/package*.json ./
RUN npm ci --quiet
COPY service/frontend/ ./
RUN npm run build

# ── Python service ─────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install the kairos-ontology toolkit
COPY . /repo
RUN pip install --no-cache-dir /repo

# Install service dependencies
COPY service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy service code
COPY service/app /app/app

# Copy compiled React frontend
COPY --from=frontend-build /frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
