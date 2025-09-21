# Use a slim Python image that brings all runtime libs
FROM python:3.12-slim

# 1️⃣ Install build tools and PostgreSQL client dev package
RUN apt-get update && \
    apt-get install -y gcc libpq-dev && \
    pip install -r /tmp/requirements.txt

# 2️⃣ Copy the whole repo into the container
WORKDIR /app
COPY . .

# 3️⃣ Expose FastAPI port (Railway expects 8000)
EXPOSE 8000

# 4️⃣ Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0", "--port", "8000"]
