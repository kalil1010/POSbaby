from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from routers import cards
from database import engine, Base
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, List
import uuid

# Try to load ML model
try:
    from joblib import load
    vectorizer, rf_model = load("apdu_model.joblib")
    logging.info("✅ Loaded APDU ML model")
except Exception as e:
    vectorizer, rf_model = None, None
    logging.warning(f"⚠️ ML model not available: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="POS-to-NFC API with APDU Processing",
    version="2.1.0",
    description="Enhanced FastAPI backend with real-time APDU processing capabilities"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB
Base.metadata.create_all(engine)

# Connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.device_info: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_connections[device_id] = websocket
        self.device_info[device_id] = {
            "connected_at": datetime.utcnow(),
            "last_activity": datetime.utcnow(),
            "apdu_count": 0
        }
        logger.info(f"📱 Device {device_id} connected")

    def disconnect(self, device_id: str):
        self.active_connections.pop(device_id, None)
        self.device_info.pop(device_id, None)
        logger.info(f"📱 Device {device_id} disconnected")

    async def send_personal_message(self, message: dict, device_id: str):
        ws = self.active_connections.get(device_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
                self.device_info[device_id]["last_activity"] = datetime.utcnow()
            except Exception as e:
                logger.error(f"❌ Send error to {device_id}: {e}")
                self.disconnect(device_id)

    def get_connected_devices(self) -> List[str]:
        return list(self.active_connections.keys())

manager = ConnectionManager()

# APDU Processor (Fixed)
class APDUProcessor:
    def __init__(self):
        self.command_history: List[dict] = []
        self.emv_commands = {
            "SELECT": "00A40400",
            "GPO": "80A80000",
            "READ_RECORD": "00B2",
            "GET_DATA": "80CA",
            "GENERATE_AC": "80AE"
        }
        self.emv_responses = {
            "SUCCESS": "9000",
            "FILE_NOT_FOUND": "6A82",
            "CMD_NOT_SUPPORTED": "6D00",
            "COND_NOT_SAT": "6985"
        }
        # PSE and AID database
        self.pse_aid = "325041592E5359532E4444463031"
        self.aid_database = {
            "A0000000031010": "VISA",
            "A0000000041010": "MASTERCARD", 
            "A000000025010901": "AMEX",
            "A0000001524010": "DISCOVER"
        }

    async def process_apdu(self, cmd: str, card_data: dict = None) -> str:
        cmd = cmd.upper().replace(" ", "")
        self.command_history.append({
            "timestamp": datetime.utcnow().isoformat(), 
            "command": cmd
        })
        logger.info(f"🔵 Processing: {cmd}")

        if cmd.startswith(self.emv_commands["SELECT"]):
            response = self.handle_select(cmd, card_data)
        elif cmd.startswith(self.emv_commands["GPO"]):
            response = self.handle_gpo(cmd, card_data)
        elif cmd.startswith(self.emv_commands["READ_RECORD"]):
            response = self.handle_read_record(cmd, card_data)
        elif cmd.startswith(self.emv_commands["GET_DATA"]):
            response = self.handle_get_data(cmd, card_data)
        else:
            response = self.emv_responses["CMD_NOT_SUPPORTED"]

        # Log APDU
        try:
            from apdu_logger import log_apdu
            success = response.endswith(self.emv_responses["SUCCESS"])
            log_apdu("ws_device", cmd, response, success)
        except ImportError:
            pass

        # ML adjustment
        if vectorizer and rf_model:
            try:
                combo = f"{cmd}|{response}"
                prob = rf_model.predict_proba(vectorizer.transform([combo]))
                if prob < 0.5:
                    logger.warning(f"🤖 ML suggests alternative response")
                    response = self.emv_responses["FILE_NOT_FOUND"]
            except Exception as e:
                logger.error(f"❌ ML error: {e}")

        logger.info(f"🟢 Response: {response}")
        return response

    def handle_select(self, cmd: str, card_data: dict = None) -> str:
        # Extract AID from command
        try:
            length = int(cmd[10:12], 16) * 2
            aid = cmd[12:12+length] if len(cmd) >= 12 + length else ""
            logger.info(f"📱 SELECT AID: {aid}")
            
            # Handle PSE
            if aid.upper() == self.pse_aid:
                logger.info("🏦 PSE Directory requested")
                # Build minimal PSE FCI
                df_name = "315041592E5359532E4444463031"  # "1PAY.SYS.DDF01"
                fci = f"6F0E84{len(df_name)//2:02X}{df_name}"
                return fci + self.emv_responses["SUCCESS"]
            
            # Handle application AIDs
            if aid in self.aid_database:
                app_name = self.aid_database[aid]
                logger.info(f"✅ AID found: {app_name}")
                # Build application FCI
                aid_tag = f"84{len(aid)//2:02X}{aid}"
                label_hex = app_name.encode().hex().upper()
                label_tag = f"50{len(label_hex)//2:02X}{label_hex}"
                fci = f"6F{(len(aid_tag + label_tag)//2):02X}{aid_tag}{label_tag}"
                return fci + self.emv_responses["SUCCESS"]
            
            logger.warning(f"❌ AID not supported: {aid}")
            return self.emv_responses["FILE_NOT_FOUND"]
            
        except Exception as e:
            logger.error(f"❌ SELECT error: {e}")
            return self.emv_responses["COND_NOT_SAT"]

    def handle_gpo(self, cmd: str, card_data: dict = None) -> str:
        logger.info("💳 GPO requested")
        # Simple GPO response
        aip = "5800"
        afl = "08010100"
        data = f"82{len(aip)//2:02X}{aip}94{len(afl)//2:02X}{afl}"
        response = f"77{len(data)//2:02X}{data}"
        return response + self.emv_responses["SUCCESS"]

    def handle_read_record(self, cmd: str, card_data: dict = None) -> str:
        logger.info("📄 READ RECORD requested")
        # Simple record with PAN and expiry
        pan = "4111111111111111"
        exp = "2501"
        if card_data:
            pan = card_data.get("pan", pan)
            exp_date = card_data.get("expiry", "2025-01-01")
            exp = exp_date[2:4] + exp_date[5:7] if "-" in exp_date else "2501"
            
        pan_tag = f"5A{len(pan)//2:02X}{pan}"
        exp_tag = f"5F24030{exp}"
        record_data = pan_tag + exp_tag
        record = f"70{len(record_data)//2:02X}{record_data}"
        return record + self.emv_responses["SUCCESS"]

    def handle_get_data(self, cmd: str, card_data: dict = None) -> str:
        tag = cmd[6:10] if len(cmd) >= 10 else ""
        logger.info(f"📊 GET DATA: {tag}")
        
        responses = {
            "9F36": "9F36020001",  # ATC
            "9F13": "9F13020001",  # Last Online ATC
            "9F17": "9F170103"     # PIN Try Counter
        }
        
        if tag.upper() in responses:
            return responses[tag.upper()] + self.emv_responses["SUCCESS"]
        
        return self.emv_responses["FILE_NOT_FOUND"]

apdu_processor = APDUProcessor()

# Include routers
app.include_router(cards.router)

@app.get("/")
async def root():
    return {
        "message": "POS-to-NFC API Enhanced", 
        "version": "2.1.0",
        "status": "✅ Ready for EMV transactions"
    }

@app.get("/status")
async def status():
    return {
        "connected_devices": manager.get_connected_devices(),
        "device_count": len(manager.get_connected_devices()),
        "apdu_commands_processed": len(apdu_processor.command_history),
        "supported_aids": list(apdu_processor.aid_database.keys())
    }

@app.websocket("/ws/apdu")
async def websocket_endpoint(ws: WebSocket):
    device_id = str(uuid.uuid4())
    await manager.connect(ws, device_id)
    
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            
            if msg.get("type") == "apdu_command":
                cmd = msg["command"]
                card_data = msg.get("card_data")
                resp = await apdu_processor.process_apdu(cmd, card_data)
                await manager.send_personal_message({
                    "type": "apdu_response", 
                    "response": resp,
                    "command": cmd
                }, device_id)
            else:
                await manager.send_personal_message({
                    "type": "error", 
                    "message": "Unknown message type"
                }, device_id)
                
    except WebSocketDisconnect:
        manager.disconnect(device_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        manager.disconnect(device_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
