# Lightweight Python image (fast to pull)
FROM python:3.12-slim

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Download Chromium for Playwright
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# RelaxDev expects port 8080
EXPOSE 8080

# Use JSON CMD format (recommended by Docker) and run through xvfb-run
# so that Chromium has a virtual display available.
CMD ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]