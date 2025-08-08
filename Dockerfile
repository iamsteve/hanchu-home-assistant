# Base image with Python
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install OS-level dependencies
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    unzip \
    gnupg \
    xvfb \
    chromium=113.0.5672.63-1~deb11u1 \
    chromium-driver=113.0.5672.63-1~deb11u1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set environment variable for Chrome binary
ENV CHROME_BIN=/usr/bin/chromium

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY app/ .

# Expose FastAPI port
EXPOSE 5322

# Run the app
CMD ["python", "main.py"]