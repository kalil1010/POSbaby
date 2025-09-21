from fastapi import FastAPI
from routers import cards

app = FastAPI(title="POS‑to‑NFC API", version="0.1")

# Register the router
app.include_router(cards.router)

# Optional: create DB tables on first start (good for dev)
if __name__ == "__main__":
    import uvicorn
    # Create all tables
    from database import engine, Base
    Base.metadata.create_all(engine)
    uvicorn.run(app, host="0.0.0", port=8000, reload=True)
