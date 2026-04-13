FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies first — separate layer for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium browser + every system dependency it needs in one shot.
# playwright install --with-deps handles the full apt-get + browser download.
RUN playwright install --with-deps chromium

# Copy application source
COPY . .

# Persistent volume for SQLite DB — mount a Railway volume at /app/data
RUN mkdir -p /app/data
ENV DATA_DIR=/app/data

EXPOSE 8501

# Shell form so ${PORT:-8501} is expanded at runtime.
# Railway injects $PORT automatically; fallback to 8501 locally.
CMD streamlit run app.py \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.fileWatcherType=none
