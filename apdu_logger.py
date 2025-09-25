from sqlalchemy import Column,Integer,String,DateTime,Text,Boolean
from database import Base,engine,SessionLocal
from datetime import datetime

class APDULog(Base):
    __tablename__="apdu_log"
    id=Column(Integer,primary_key=True)
    device_id=Column(String)
    apdu_command=Column(Text)
    apdu_response=Column(Text)
    success=Column(Boolean)
    timestamp=Column(DateTime,default=datetime.utcnow)

Base.metadata.create_all(engine)

def log_apdu(device_id,cmd,rsp,success):
    db=SessionLocal()
    db.add(APDULog(device_id=device_id,apdu_command=cmd,
        apdu_response=rsp,success=success))
    db.commit();db.close()
