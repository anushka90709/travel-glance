FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer is cached unless requirements change.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

# travel.db and uploads/ are runtime data, not part of the image - see the
# volume mounts in the run command in README/deployment notes. This just
# gives uploads/ somewhere to exist before a volume is mounted over it.
RUN mkdir -p uploads

EXPOSE 5000

WORKDIR /app/backend
CMD ["python", "serve.py"]
