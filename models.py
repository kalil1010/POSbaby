from sqlalchemy import Column, Integer, String, Date, Numeric
from database import Base

class Card(Base):
    __tablename__ = "cards"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    holder_name = Column(String(128), nullable=False)
    pan         = Column(String(16), nullable=False)
    expiry      = Column(Date, nullable=False)
    cvv         = Column(Integer, nullable=False)
    issuer_id   = Column(String(6), nullable=False)
    track       = Column(String(4), nullable=False)
    amount      = Column(Numeric(10,2), default=0.00)

    def __repr__(self) -> str:
        return f"<Card {self.id} – {self.holder_name}>"
