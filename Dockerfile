FROM python:3.14-slim

WORKDIR /app

# Install dependencies first so the layer is cached across rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code, persona, and config.
COPY . .

CMD ["python", "main.py"]
