# Use a slim Python image that brings all runtime libs
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# 1️⃣ Copy requirements.txt first (for better Docker layer caching)
COPY requirements.txt .

# 2️⃣ Install build tools and PostgreSQL client dev package, then install Python packages
RUN apt-get update && \
    apt-get install -y gcc libpq-dev && \
    pip install --no-cache-dir -r requirements.txt && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 3️⃣ Copy the whole repo into the container
COPY . .

# 4️⃣ Expose FastAPI port (Railway expects 8000)
EXPOSE 8000

# 5️⃣ Start the server (fixed host IP)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
