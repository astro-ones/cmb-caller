import os
import sys
import json
import time
import asyncio
import logging
import uvicorn
import websockets
from datetime import datetime
from fastapi import FastAPI, WebSocket, Request
from fastapi.websockets import WebSocketDisconnect, WebSocketState
from fastapi.responses import JSONResponse

# =================================================================
# [系統配置] - 直接修改這裡
# =================================================================
VER = "20260212_PROD_READY"
PORT = 38000
# 指向你的 CMB Main Server 實體位址
MAIN_SERVER_URL = "ws://YOUR_MAIN_SERVER_IP:8088" 
VENDOR_ID = "tawe"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("CMB-Frontend")

# =================================================================
# [三方屏蔽區] - 僅此部分改為 Log，不影響主邏輯
# =================================================================
def line_notify(msg):
    logger.info(f"【LINE NOTIFY】: {msg}")

def pubsub_broadcast(action, msg):
    logger.info(f"【PUBSUB MOCK】: {action} - {msg}")

# =================================================================
# [核心組件] - 記憶體管理與連線管理
# =================================================================
class JSONMemoryManager:
    def __init__(self):
        self.records = []
        self._lock = asyncio.Lock()
    async def add(self, data):
        async with self._lock:
            item = json.loads(data) if isinstance(data, str) else data
            item["_ts"] = time.time()
            self.records.append(item)
            if len(self.records) > 50: self.records.pop(0)
    async def search(self, condition):
        async with self._lock:
            return [r for r in self.records if condition(r)]
    async def remove(self, items):
        async with self._lock:
            self.records = [r for r in self.records if r not in items]

manager = JSONMemoryManager()

class ClientManager:
    def __init__(self):
        self.clients = {} # caller_id -> {connections, caller_num}
        self._lock = asyncio.Lock()
    async def add(self, cid, ws, ws_type):
        async with self._lock:
            if cid not in self.clients:
                self.clients[cid] = {"connections": {}, "caller_num": 0}
            self.clients[cid]["connections"][ws] = {"ws_type": ws_type}
    async def remove(self, cid, ws):
        async with self._lock:
            if cid in self.clients and ws in self.clients[cid]["connections"]:
                del self.clients[cid]["connections"][ws]
    async def update_num(self, cid, num):
        async with self._lock:
            if cid in self.clients: self.clients[cid]["caller_num"] = num

client_manager = ClientManager()

# =================================================================
# [Main Server WebSocket Client] - 主動連向中央
# =================================================================
class MainServerClient:
    def __init__(self, url):
        self.url = url
        self.ws = None
    async def connect(self):
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    self.ws = ws
                    logger.info(f"成功連線至 Main Server: {self.url}")
                    async for msg in ws:
                        await manager.add(msg)
                        logger.info(f"從 Main Server 收到: {msg}")
            except Exception as e:
                logger.error(f"Main Server 連線中斷: {e}，3秒後重試...")
                await asyncio.sleep(3)
    async def send(self, data):
        if self.ws: await self.ws.send(json.dumps(data))

main_client = MainServerClient(MAIN_SERVER_URL)

# =================================================================
# [FastAPI 應用] - HTTP 路由與 WebSocket Server
# =================================================================
app = FastAPI()

@app.get("/")
async def root():
    return {"service": "cmb-caller-frontend", "version": VER}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/status")
async def get_status():
    clients = await client_manager.get_all_clients()
    return {"active_ids": list(clients.keys()), "count": len(clients)}

@app.post("/trigger")
async def trigger_action(request: Request):
    """實體 POST 路由，可接收外部 API 觸發"""
    data = await request.json()
    logger.info(f"收到 POST 觸發: {data}")
    await main_client.send(data) # 轉發給 Main Server
    return {"result": "Action triggered to Main Server"}

@app.websocket("/")
async def websocket_handler(ws: WebSocket):
    await ws.accept()
    cid = None
    try:
        while True:
            raw_msg = await ws.receive_text()
            # 1. 簡易解析 (CSV: id,cmd,param)
            parts = raw_msg.split(",")
            if len(parts) >= 2:
                cid, cmd = parts[0], parts[1]
                # 2. 處理驗證
                if cmd == "auth":
                    await client_manager.add(cid, ws, 1)
                    await ws.send_text(f"OK,{cid},auth")
                    await main_client.send({"action": "login", "caller_id": cid})
                # 3. 處理叫號
                elif cid and cmd.isdigit():
                    num = int(cmd)
                    await client_manager.update_num(cid, num)
                    await main_client.send({"action": "call_number", "caller_id": cid, "call_num": num})
                    await ws.send_text(f"OK,{cid},{num},send")
    except WebSocketDisconnect:
        if cid: await client_manager.remove(cid, ws)

# =================================================================
# [執行進入點]
# =================================================================
async def periodic_sync():
    """例行資料同步至 Main Server"""
    while True:
        clients = await client_manager.get_all_clients()
        for cid, info in clients.items():
            await main_client.send({
                "vendor_id": VENDOR_ID, "caller_id": cid, 
                "call_num": info["caller_num"], "change": False
            })
        await asyncio.sleep(60)

async def main():
    # 啟動連向 Main Server 的任務
    asyncio.create_task(main_client.connect())
    # 啟動例行同步任務
    asyncio.create_task(periodic_sync())
    # 啟動 FastAPI (含 HTTP 與 WebSocket Server)
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())