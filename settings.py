import os

# Get connection string from env var (Railway will inject DATABASE_URL)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:kPpJhIbufBFZGPsHkBFWXYujJREVQQwd@postgres.railway.internal:5432/railway")

