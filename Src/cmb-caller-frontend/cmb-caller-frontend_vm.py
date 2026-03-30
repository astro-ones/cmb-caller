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
from fastapi.websockets import WebSocketDisconnect
from fastapi.responses import JSONResponse

# =================================================================
# [系統配置] - 請根據你的實體環境修改 MAIN_SERVER_URL
# =================================================================
VER = "20260212_FINAL_STABLE"
PORT = 38000
# 這是你要「對接」的舊中心伺服器位址
MAIN_SERVER_URL = "ws://127.0.0.1:8088" 
VENDOR_ID = "tawe"

# 解決 Windows 控制台輸出編碼問題
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("CMB-Bridge")

# =================================================================
# [管理組件] - 負責狀態儲存與搜尋回覆
# =================================================================
class JSONMemoryManager:
    """暫存來自中央伺服器的回覆資料"""
    def __init__(self):
        self.records = []
        self._lock = asyncio.Lock()
    async def add(self, data):
        async with self._lock:
            item = json.loads(data) if isinstance(data, str) else data
            item["_ts"] = time.time()
            self.records.append(item)
            if len(self.records) > 30: self.records.pop(0) # 保持最新 30 筆
    def get_all(self):
        return self.records

manager = JSONMemoryManager()

class ClientManager:
    """管理目前連入本機的機台連線"""
    def __init__(self):
        self.clients = {} # caller_id -> {connections, last_num}
        self._lock = asyncio.Lock()

    async def add(self, cid, ws):
        async with self._lock:
            if cid not in self.clients:
                self.clients[cid] = {"connections": set(), "last_num": 0}
            self.clients[cid]["connections"].add(ws)

    async def remove(self, cid, ws):
        async with self._lock:
            if cid in self.clients:
                self.clients[cid]["connections"].discard(ws)

    async def update_num(self, cid, num):
        async with self._lock:
            if cid in self.clients: self.clients[cid]["last_num"] = num

    async def get_all_clients(self):
        """回傳目前所有連線中機台的快照 (修正後的函式名)"""
        async with self._lock:
            return {cid: info.copy() for cid, info in self.clients.items()}

client_manager = ClientManager()

# =================================================================
# [Main Server 連線客戶端] - 負責轉拋任務
# =================================================================
class MainServerClient:
    """主動連向中央舊伺服器，負責把資料『轉拋』出去"""
    def __init__(self, url):
        self.url = url
        self.ws = None

    async def connect_loop(self):
        """保持與中央伺服器的長連線，斷線自動重連"""
        while True:
            try:
                logger.info(f"正在建立與中央伺服器的通訊橋樑: {self.url}")
                async with websockets.connect(self.url) as ws:
                    self.ws = ws
                    logger.info("✅ 已成功連接中央伺服器，轉拋功能就緒。")
                    async for msg in ws:
                        await manager.add(msg)
                        logger.info(f"⬅️ [從中央接收]: {msg}")
            except Exception as e:
                logger.error(f"❌ 中央伺服器連線中斷: {e}，5秒後重新建立橋樑...")
                self.ws = None
                await asyncio.sleep(5)

    async def send(self, data):
        """將資料封裝並實體發送至中央伺服器"""
        if self.ws:
            try:
                await self.ws.send(json.dumps(data))
                logger.info(f"➡️ [轉拋至中央]: {data}")
                return True
            except:
                return False
        return False

main_client = MainServerClient(MAIN_SERVER_URL)

# =================================================================
# [FastAPI 伺服器] - 處理機台 WebSocket 與外部 HTTP API
# =================================================================
app = FastAPI()

@app.get("/")
async def root():
    return {"service": "cmb-caller-bridge", "version": VER, "main_server": MAIN_SERVER_URL}

@app.get("/health")
async def health():
    return {"status": "healthy", "server_time": datetime.now().isoformat()}

@app.get("/status")
@app.get("/info")
async def status():
    """查看目前有哪些機台 ID 成功連入本機並進行轉發"""
    stats = await client_manager.get_all_clients()
    return {
        "active_devices": len(stats),
        "details": {cid: {"connections": len(info["connections"]), "last_num": info["last_num"]} for cid, info in stats.items()}
    }

@app.get("/show_all_back_data")
async def show_data():
    """顯示最近從中央伺服器傳回的資料"""
    return {"status": "OK", "records": manager.get_all()}

@app.post("/trigger")
async def trigger(request: Request):
    """實體 POST 介面：接收外部指令並立刻轉拋給中央伺服器"""
    try:
        body = await request.json()
        success = await main_client.send(body)
        return {"result": "success" if success else "failed (bridge offline)", "payload": body}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.websocket("/")
async def ws_handler(ws: WebSocket):
    """機台連入點：處理 CSV 並轉拋為 JSON"""
    await ws.accept()
    current_cid = None
    try:
        while True:
            raw_data = await ws.receive_text()
            # 1. 解析機台 CSV 格式 (例如: z0001,auth,pwd)
            parts = raw_data.split(",")
            if len(parts) >= 2:
                cid, cmd = parts[0], parts[1]
                current_cid = cid
                
                # 2. 處理握手驗證
                if cmd == "auth":
                    await client_manager.add(cid, ws)
                    await ws.send_text(f"OK,{cid},auth")
                    # 轉拋登入訊息給中央
                    await main_client.send({"action": "login", "caller_id": cid, "uuid": "BRIDGE_MODE"})
                
                # 3. 處理叫號轉發
                elif cmd.isdigit(): 
                    num = int(cmd)
                    await client_manager.update_num(cid, num)
                    # 將 CSV 叫號轉換為 JSON 實體轉拋給中央
                    await main_client.send({
                        "action": "call_number", 
                        "caller_id": cid, 
                        "call_num": num,
                        "vendor_id": VENDOR_ID
                    })
                    await ws.send_text(f"OK,{cid},{num},send")
    except WebSocketDisconnect:
        if current_cid:
            await client_manager.remove(current_cid, ws)
            logger.info(f"機台設備 {current_cid} 已從橋樑斷開")

# =================================================================
# [背景同步任務]
# =================================================================
async def periodic_sync():
    """每分鐘定時向中央伺服器同步機台狀態"""
    while True:
        try:
            clients = await client_manager.get_all_clients()
            for cid, info in clients.items():
                await main_client.send({
                    "vendor_id": VENDOR_ID,
                    "caller_id": cid, 
                    "call_num": str(info["last_num"]),
                    "change": False,
                    "uuid": "PERIODIC_SYNC"
                })
        except Exception as e:
            logger.error(f"背景同步任務異常: {e}")
        await asyncio.sleep(60)

async def main():
    # 啟動對中央伺服器的連線
    asyncio.create_task(main_client.connect_loop())
    # 啟動定時同步任務
    asyncio.create_task(periodic_sync())
    # 啟動本機 API 與機台監聽埠
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("橋樑服務已手動關閉")