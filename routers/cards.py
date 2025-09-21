from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from database import SessionLocal
from models import Card
from schemas import CardCreate, CardRead

router = APIRouter(prefix="/cards", tags=["Cards"])

# ------------- CRUD ---------------

def get_session() -> Session:
    return SessionLocal()

@router.get("/", response_model=List[CardRead])
def read_cards(session: Session = Depends(get_session)):
    return session.query(Card).all()

@router.post("/", response_model=CardRead, status_code=201)
def create_card(card: CardCreate, session: Session = Depends(get_session)):
    db_card = Card(
        holder_name  = card.holder_name,
        pan          = card.pan,
        expiry       = card.expiry,
        cvv          = card.cvv,
        issuer_id    = card.issuer_id,
        track        = card.track,
        amount       = card.amount,
    )
    session.add(db_card)
    session.commit()
    session.refresh(db_card)
    return db_card
