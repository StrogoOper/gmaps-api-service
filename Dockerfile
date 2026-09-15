# Playwright Python image with Chromium pre-installed
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Render uses $PORT env variable, default to 8000
EXPOSE 8000

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}