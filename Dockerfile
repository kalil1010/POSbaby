# Use a slim Python image that comes with libpq for Postgres
FROM python:3.12-slim

# Install dependencies
COPY requirements.txt /tmp/
RUN pip install -r /tmp/requirements.txt

# Copy application code into the container
WORKDIR /app
COPY . .

# Expose FastAPI port (Railway expects 8000 by default)
EXPOSE 8000

# Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0", "--port", "8000"]
