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
from apdu_logger import log_apdu
from joblib import load

# Load ML model if present
try:
    vectorizer, rf_model = load("apdu_model.joblib")
    logging.info("Loaded APDU ML model")
except:
    vectorizer, rf_model = None, None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="POS-to-NFC API with APDU Processing",
    version="2.0.0",
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
        logger.info(f"Device {device_id} connected via WebSocket")

    def disconnect(self, device_id: str):
        self.active_connections.pop(device_id, None)
        self.device_info.pop(device_id, None)
        logger.info(f"Device {device_id} disconnected")

    async def send_personal_message(self, message: dict, device_id: str):
        ws = self.active_connections.get(device_id)
        if ws:
            try:
                await ws.send_text(json.dumps(message))
                self.device_info[device_id]["last_activity"] = datetime.utcnow()
            except Exception as e:
                logger.error(f"Error sending to {device_id}: {e}")
                self.disconnect(device_id)

    def get_connected_devices(self) -> List[str]:
        return list(self.active_connections.keys())

manager = ConnectionManager()

# APDU Processor
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
        # AID DB
        self.aid_database = {
            "A0000000031010": "VISA",
            "A0000000041010": "MASTERCARD",
            "A000000025010901": "AMEX",
            "A0000001524010": "DISCOVER"
        }

    async def process_apdu(self, cmd: str, card_data: dict = None) -> str:
        cmd = cmd.upper().replace(" ", "")
        self.command_history.append({"timestamp": datetime.utcnow().isoformat(), "command": cmd})
        logger.info(f"Processing APDU: {cmd}")

        if cmd.startswith(self.emv_commands["SELECT"]):
            response = self.handle_select(cmd)
        elif cmd.startswith(self.emv_commands["GPO"]):
            response = self.handle_gpo(cmd)
        elif cmd.startswith(self.emv_commands["READ_RECORD"]):
            response = self.handle_read_record(cmd)
        elif cmd.startswith(self.emv_commands["GET_DATA"]):
            response = self.handle_get_data(cmd)
        elif cmd.startswith(self.emv_commands["GENERATE_AC"]):
            response = self.handle_generate_ac(cmd)
        else:
            response = self.emv_responses["CMD_NOT_SUPPORTED"]

        # Log
        log_apdu("ws_device", cmd, response, response.endswith(self.emv_responses["SUCCESS"]))

        # ML adjustment
        if vectorizer and rf_model:
            combo = f"{cmd}|{response}"
            prob = rf_model.predict_proba(vectorizer.transform([combo]))[0][1]
            if prob < 0.5:
                response = self.emv_responses["FILE_NOT_FOUND"]

        return response

    def handle_select(self, cmd: str) -> str:
        length = int(cmd[10:12], 16) * 2
        aid = cmd.substring(12, 12 + length)
        if aid in self.aid_database:
            fci = "6F108407" + aid + "A5049F6501FF"  # minimal FCI
            return fci + self.emv_responses["SUCCESS"]
        return self.emv_responses["FILE_NOT_FOUND"]

    def handle_gpo(self, cmd: str) -> str:
        return "771082028000" + self.emv_responses["SUCCESS"]

    def handle_read_record(self, cmd: str) -> str:
        record = "70105A0850123456789012345F24031234"
        return record + self.emv_responses["SUCCESS"]

    def handle_get_data(self, cmd: str) -> str:
        return "9F36020001" + self.emv_responses["SUCCESS"]

    def handle_generate_ac(self, cmd: str) -> str:
        return "9F270180" + self.emv_responses["SUCCESS"]

apdu_processor = APDUProcessor()

# Include routers
app.include_router(cards.router)

@app.get("/")
async def root():
    return {"message": "POS-to-NFC API", "version": "2.0.0"}

@app.get("/status")
async def status():
    return {
        "devices": manager.get_connected_devices(),
        "apdus": len(apdu_processor.command_history)
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
                resp = await apdu_processor.process_apdu(cmd, msg.get("card_data"))
                await manager.send_personal_message({"type": "apdu_response", "response": resp}, device_id)
            else:
                await manager.send_personal_message({"type": "error", "message": "Unknown type"}, device_id)
    except WebSocketDisconnect:
        manager.disconnect(device_id)
