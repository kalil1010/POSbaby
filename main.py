from fastapi import FastAPI
from routers import cards

# Import database components at the top
from database import engine, Base

app = FastAPI(title="POS‑to‑NFC API", version="0.1")

# Create all tables on startup (moved outside if __name__ block)
Base.metadata.create_all(engine)

# Register the router
app.include_router(cards.router)

# Optional: for local development
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
