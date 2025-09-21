from pydantic import BaseModel
from datetime import date

class CardBase(BaseModel):
    holder_name: str
    pan: str
    expiry: date
    cvv: int
    issuer_id: str
    track: str
    amount: float | None = 0.00

class CardCreate(CardBase):
    pass          # POST payload – same as CardBase

class CardRead(CardBase):
    id: int

    class Config:
        orm_mode = True
