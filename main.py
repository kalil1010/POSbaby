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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="POS-to-NFC API with APDU Processing",
    version="2.0.0",
    description="Enhanced FastAPI backend with real-time APDU processing capabilities"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables
Base.metadata.create_all(engine)

# WebSocket connection manager
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
        if device_id in self.active_connections:
            del self.active_connections[device_id]
        if device_id in self.device_info:
            del self.device_info[device_id]
        logger.info(f"Device {device_id} disconnected")
    
    async def send_personal_message(self, message: dict, device_id: str):
        if device_id in self.active_connections:
            try:
                await self.active_connections[device_id].send_text(json.dumps(message))
                self.device_info[device_id]["last_activity"] = datetime.utcnow()
            except Exception as e:
                logger.error(f"Error sending message to {device_id}: {e}")
                self.disconnect(device_id)
    
    async def broadcast(self, message: dict):
        disconnected = []
        for device_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting to {device_id}: {e}")
                disconnected.append(device_id)
        
        for device_id in disconnected:
            self.disconnect(device_id)
    
    def get_connected_devices(self) -> List[str]:
        return list(self.active_connections.keys())

manager = ConnectionManager()

# APDU Processing Engine
class APDUProcessor:
    def __init__(self):
        self.command_history: List[Dict] = []
        
        # EMV Command patterns
        self.emv_commands = {
            "SELECT": "00A40400",
            "GET_PROCESSING_OPTIONS": "80A80000", 
            "READ_RECORD": "00B2",
            "GET_DATA": "80CA",
            "GENERATE_AC": "80AE",
            "EXTERNAL_AUTHENTICATE": "0082",
            "INTERNAL_AUTHENTICATE": "0088"
        }
        
        # EMV Response templates
        self.emv_responses = {
            "SUCCESS": "9000",
            "FILE_NOT_FOUND": "6A82",
            "COMMAND_NOT_SUPPORTED": "6D00",
            "CONDITIONS_NOT_SATISFIED": "6985",
            "WRONG_LENGTH": "6700",
            "SECURITY_STATUS_NOT_SATISFIED": "6982"
        }
        
        # AID database
        self.aid_database = {
            "A0000000031010": {
                "name": "VISA",
                "type": "credit",
                "country": "US",
                "issuer": "VISA Inc."
            },
            "A0000000041010": {
                "name": "MASTERCARD",
                "type": "credit", 
                "country": "US",
                "issuer": "Mastercard Inc."
            },
            "A000000025010901": {
                "name": "AMEX",
                "type": "credit",
                "country": "US", 
                "issuer": "American Express"
            },
            "A0000001524010": {
                "name": "DISCOVER",
                "type": "credit",
                "country": "US",
                "issuer": "Discover"
            }
        }
    
    async def process_apdu(self, command_hex: str, card_data: dict = None) -> str:
        """
        Process APDU command and return appropriate EMV response
        """
        try:
            command_hex = command_hex.upper().replace(" ", "")
            
            # Log command
            self.command_history.append({
                "timestamp": datetime.utcnow().isoformat(),
                "command": command_hex,
                "type": self.identify_command_type(command_hex)
            })
            
            logger.info(f"Processing APDU: {command_hex}")
            
            # Route to appropriate handler
            if self.is_select_command(command_hex):
                return await self.handle_select(command_hex, card_data)
            elif self.is_gpo_command(command_hex):
                return await self.handle_get_processing_options(command_hex, card_data)
            elif self.is_read_record_command(command_hex):
                return await self.handle_read_record(command_hex, card_data)
            elif self.is_get_data_command(command_hex):
                return await self.handle_get_data(command_hex, card_data)
            elif self.is_generate_ac_command(command_hex):
                return await self.handle_generate_ac(command_hex, card_data)
            else:
                logger.warning(f"Unknown APDU command: {command_hex}")
                return self.emv_responses["COMMAND_NOT_SUPPORTED"]
                
        except Exception as e:
            logger.error(f"Error processing APDU {command_hex}: {e}")
            return self.emv_responses["CONDITIONS_NOT_SATISFIED"]
    
    def identify_command_type(self, command_hex: str) -> str:
        for cmd_type, pattern in self.emv_commands.items():
            if command_hex.startswith(pattern):
                return cmd_type
        return "UNKNOWN"
    
    def is_select_command(self, command: str) -> bool:
        return command.startswith(self.emv_commands["SELECT"])
    
    def is_gpo_command(self, command: str) -> bool:
        return command.startswith(self.emv_commands["GET_PROCESSING_OPTIONS"])
    
    def is_read_record_command(self, command: str) -> bool:
        return command.startswith(self.emv_commands["READ_RECORD"])
    
    def is_get_data_command(self, command: str) -> bool:
        return command.startswith(self.emv_commands["GET_DATA"])
    
    def is_generate_ac_command(self, command: str) -> bool:
        return command.startswith(self.emv_commands["GENERATE_AC"])
    
    async def handle_select(self, command_hex: str, card_data: dict = None) -> str:
        """Handle SELECT application command"""
        try:
            # Extract AID from command
            if len(command_hex) < 12:
                return self.emv_responses["WRONG_LENGTH"]
            
            aid_length = int(command_hex[10:12], 16) * 2
            if len(command_hex) < 12 + aid_length:
                return self.emv_responses["WRONG_LENGTH"]
            
            requested_aid = command_hex[12:12+aid_length]
            logger.info(f"SELECT AID requested: {requested_aid}")
            
            # Check if AID is supported
            if requested_aid in self.aid_database:
                aid_info = self.aid_database[requested_aid]
                logger.info(f"AID found: {aid_info['name']}")
                
                # Build FCI response
                fci_response = self.build_fci_response(requested_aid, aid_info, card_data)
                return fci_response + self.emv_responses["SUCCESS"]
            else:
                logger.warning(f"AID not found: {requested_aid}")
                return self.emv_responses["FILE_NOT_FOUND"]
                
        except Exception as e:
            logger.error(f"Error in SELECT handler: {e}")
            return self.emv_responses["CONDITIONS_NOT_SATISFIED"]
    
    def build_fci_response(self, aid: str, aid_info: dict, card_data: dict = None) -> str:
        """Build File Control Information response"""
        try:
            # Application Label
            app_name = aid_info["name"]
            app_label = "50" + f"{len(app_name):02X}" + app_name.encode().hex().upper()
            
            # Application Preferred Name  
            app_pref_name = "9F12" + f"{len(app_name):02X}" + app_name.encode().hex().upper()
            
            # Application Priority Indicator
            app_priority = "870101"
            
            # Language Preference
            lang_pref = "5F2D02656E"  # English
            
            # Issuer Code Table Index
            issuer_code = "9F110101"
            
            # Build A5 template
            a5_data = app_label + app_pref_name + app_priority + lang_pref + issuer_code
            a5_template = "A5" + f"{len(a5_data)//2:02X}" + a5_data
            
            # Application Identifier
            aid_tag = "84" + f"{len(aid)//2:02X}" + aid
            
            # Complete FCI
            fci_data = aid_tag + a5_template
            fci = "6F" + f"{len(fci_data)//2:02X}" + fci_data
            
            return fci
            
        except Exception as e:
            logger.error(f"Error building FCI: {e}")
            return "6F00"
    
    async def handle_get_processing_options(self, command_hex: str, card_data: dict = None) -> str:
        """Handle GET PROCESSING OPTIONS command"""
        try:
            # Build Application Interchange Profile (AIP)
            aip = "5800"  # Terminal verification, SDA, Terminal risk management
            
            # Build Application File Locator (AFL)
            afl = "08010100100201001802010020040100"  # Multiple records
            
            # Build response
            aip_tag = "82" + f"{len(aip)//2:02X}" + aip
            afl_tag = "94" + f"{len(afl)//2:02X}" + afl
            
            response_data = aip_tag + afl_tag
            response = "77" + f"{len(response_data)//2:02X}" + response_data
            
            logger.info(f"GPO response: {response}")
            return response + self.emv_responses["SUCCESS"]
            
        except Exception as e:
            logger.error(f"Error in GPO handler: {e}")
            return self.emv_responses["CONDITIONS_NOT_SATISFIED"]
    
    async def handle_read_record(self, command_hex: str, card_data: dict = None) -> str:
        """Handle READ RECORD command"""
        try:
            if len(command_hex) < 8:
                return self.emv_responses["WRONG_LENGTH"]
            
            record_num = int(command_hex[4:6], 16)
            sfi = int(command_hex[6:8], 16)
            
            logger.info(f"READ RECORD - Record: {record_num}, SFI: {sfi}")
            
            # Build record based on record number
            if record_num == 1:
                record = self.build_application_record(card_data)
            elif record_num == 2:
                record = self.build_track_record(card_data)
            elif record_num == 3:
                record = self.build_additional_record(card_data)
            else:
                return self.emv_responses["FILE_NOT_FOUND"]
            
            return record + self.emv_responses["SUCCESS"]
            
        except Exception as e:
            logger.error(f"Error in READ RECORD handler: {e}")
            return self.emv_responses["CONDITIONS_NOT_SATISFIED"]
    
    def build_application_record(self, card_data: dict = None) -> str:
        """Build application record with card data"""
        try:
            if not card_data:
                # Default card data
                pan = "4111111111111111"
                expiry = "2412"
                holder_name = "TEST CARDHOLDER"
            else:
                pan = card_data.get("pan", "4111111111111111")
                expiry = self.format_expiry(card_data.get("expiry", "2024-12-01"))
                holder_name = card_data.get("holder_name", "CARDHOLDER").upper().ljust(26)[:26]
            
            # Build EMV tags
            pan_tag = "5A" + f"{len(pan)//2:02X}" + pan
            expiry_tag = "5F24" + "03" + expiry + "00"
            name_tag = "5F20" + f"{len(holder_name):02X}" + holder_name.encode().hex().upper()
            service_code = "5F300201"
            discretionary = "9F200800000000000000"
            track2_equiv = "57" + f"{len(pan + 'D' + expiry + '201')//2:02X}" + pan + "D" + expiry + "201"
            
            record_data = pan_tag + expiry_tag + name_tag + service_code + discretionary + track2_equiv
            record = "70" + f"{len(record_data)//2:02X}" + record_data
            
            return record
            
        except Exception as e:
            logger.error(f"Error building application record: {e}")
            return "7000"
    
    def build_track_record(self, card_data: dict = None) -> str:
        """Build track 2 equivalent record"""
        try:
            if not card_data:
                pan = "4111111111111111"
                expiry = "2412"
            else:
                pan = card_data.get("pan", "4111111111111111")
                expiry = self.format_expiry(card_data.get("expiry", "2024-12-01"))
            
            track2_data = pan + "D" + expiry + "201"
            track2_tag = "57" + f"{len(track2_data)//2:02X}" + track2_data
            
            record = "70" + f"{len(track2_tag)//2:02X}" + track2_tag
            return record
            
        except Exception as e:
            logger.error(f"Error building track record: {e}")
            return "7000"
    
    def build_additional_record(self, card_data: dict = None) -> str:
        """Build additional application record"""
        try:
            issuer_country = "5F2803025553"  # US
            currency_code = "5F2A020348"     # USD
            app_version = "9F08060000000000"
            
            record_data = issuer_country + currency_code + app_version
            record = "70" + f"{len(record_data)//2:02X}" + record_data
            
            return record
            
        except Exception as e:
            logger.error(f"Error building additional record: {e}")
            return "7000"
    
    async def handle_get_data(self, command_hex: str, card_data: dict = None) -> str:
        """Handle GET DATA command"""
        try:
            if len(command_hex) < 10:
                return self.emv_responses["WRONG_LENGTH"]
            
            tag = command_hex[6:10]
            logger.info(f"GET DATA tag: {tag}")
            
            responses = {
                "9F13": "9F13020001",  # Last Online ATC
                "9F17": "9F170103",    # PIN Try Counter
                "9F36": "9F36020001",  # ATC
                "9F4F": "9F4F1A" + "00" * 26  # Log Format
            }
            
            if tag.upper() in responses:
                return responses[tag.upper()] + self.emv_responses["SUCCESS"]
            else:
                return self.emv_responses["FILE_NOT_FOUND"]
                
        except Exception as e:
            logger.error(f"Error in GET DATA handler: {e}")
            return self.emv_responses["CONDITIONS_NOT_SATISFIED"]
    
    async def handle_generate_ac(self, command_hex: str, card_data: dict = None) -> str:
        """Handle GENERATE AC command"""
        try:
            # Simple AC response (would need proper cryptography in production)
            cryptogram = "1234567890ABCDEF"
            atc = "0001"
            
            ac_data = "9F26" + "08" + cryptogram + "9F36" + "02" + atc + "9F10" + "04" + "0000"
            response = "77" + f"{len(ac_data)//2:02X}" + ac_data
            
            return response + self.emv_responses["SUCCESS"]
            
        except Exception as e:
            logger.error(f"Error in GENERATE AC handler: {e}")
            return self.emv_responses["CONDITIONS_NOT_SATISFIED"]
    
    def format_expiry(self, expiry_str: str) -> str:
        """Convert YYYY-MM-DD to YYMM format"""
        try:
            parts = expiry_str.split("-")
            if len(parts) == 3:
                year = parts[0][2:]
                month = parts[1]
                return year + month
            return "2501"
        except:
            return "2501"

# Initialize APDU processor
apdu_processor = APDUProcessor()

# Register routers
app.include_router(cards.router)

@app.get("/")
async def root():
    return {
        "message": "POS-to-NFC API with Enhanced APDU Processing",
        "version": "2.0.0",
        "features": [
            "Real-time APDU processing",
            "WebSocket support",
            "EMV command handling", 
            "Multi-card support",
            "Remote debugging"
        ]
    }

@app.get("/status")
async def status():
    return {
        "connected_devices": manager.get_connected_devices(),
        "device_count": len(manager.get_connected_devices()),
        "apdu_commands_processed": len(apdu_processor.command_history),
        "supported_aids": list(apdu_processor.aid_database.keys())
    }

@app.get("/apdu/history")
async def get_apdu_history():
    return {
        "commands": apdu_processor.command_history[-50:],  # Last 50 commands
        "total_commands": len(apdu_processor.command_history)
    }

@app.websocket("/ws/apdu")
async def websocket_endpoint(websocket: WebSocket):
    device_id = str(uuid.uuid4())
    await manager.connect(websocket, device_id)
    
    try:
        await manager.send_personal_message({
            "type": "status",
            "message": f"Connected as {device_id}",
            "timestamp": datetime.utcnow().isoformat()
        }, device_id)
        
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            message_type = message.get("type")
            timestamp = datetime.utcnow().isoformat()
            
            if message_type == "init":
                device_info = message.get("device_info", {})
                manager.device_info[device_id].update(device_info)
                
                await manager.send_personal_message({
                    "type": "status", 
                    "message": "Device initialized successfully",
                    "device_id": device_id,
                    "timestamp": timestamp
                }, device_id)
                
            elif message_type == "apdu_command":
                command = message.get("command", "")
                card_data = message.get("card_data")
                
                logger.info(f"Received APDU from {device_id}: {command}")
                manager.device_info[device_id]["apdu_count"] += 1
                
                # Process APDU
                response_hex = await apdu_processor.process_apdu(command, card_data)
                
                # Send response back to device
                await manager.send_personal_message({
                    "type": "apdu_response",
                    "response": response_hex,
                    "original_command": command,
                    "timestamp": timestamp,
                    "processing_time": "< 1ms"
                }, device_id)
                
                logger.info(f"Sent APDU response to {device_id}: {response_hex}")
                
            elif message_type == "heartbeat":
                await manager.send_personal_message({
                    "type": "heartbeat_response",
                    "timestamp": timestamp
                }, device_id)
                
            else:
                await manager.send_personal_message({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}",
                    "timestamp": timestamp
                }, device_id)
    
    except WebSocketDisconnect:
        logger.info(f"Device {device_id} disconnected")
        manager.disconnect(device_id)
    except Exception as e:
        logger.error(f"WebSocket error for device {device_id}: {e}")
        manager.disconnect(device_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)