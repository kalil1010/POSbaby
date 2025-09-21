from pydantic import BaseModel, ConfigDict
from datetime import date
from typing import Optional

class CardBase(BaseModel):
    holder_name: str
    pan: str
    expiry: date
    cvv: int
    issuer_id: str
    track: str
    amount: Optional[float] = 0.00

class CardCreate(CardBase):
    pass  # POST payload – same as CardBase

class CardRead(CardBase):
    id: int
    
    # Fixed Pydantic V2 configuration
    model_config = ConfigDict(from_attributes=True)
