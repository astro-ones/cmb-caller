// definitions/upstream.js
const WebSocket = require('ws');

MAIN.upstreamClient = {
    ws: null,
    targetUrl: process.env.WS_URL || 'ws://34.80.113.178:8000',
    retryDelay: 3000,
    maxRetryDelay: 30000,
    isConnected: false,

    async connect() {
        console.log(`[Upstream] 嘗試連線至 CMB Main Server: ${this.targetUrl}`);
        this.ws = new WebSocket(this.targetUrl);

        this.ws.on('open', () => {
            console.log(`[Upstream] 已連線!`);
            this.isConnected = true;
            this.retryDelay = 3000;
            this.send(JSON.stringify({ source: "tawe" }));
        });

        this.ws.on('message', async (data) => {
            const messageStr = data.toString();
            console.log(`[Upstream] 收到主伺服器訊息: ${messageStr}`);
            await this.processMessage(messageStr);
        });

        this.ws.on('close', () => {
             console.log('[Upstream] 連線中斷，準備重新連線...');
             this.isConnected = false;
             setTimeout(() => this.connect(), this.retryDelay);
             this.retryDelay = Math.min(this.retryDelay * 2, this.maxRetryDelay);
        });

        this.ws.on('error', (err) => console.error(`[Upstream] 發生錯誤:`, err.message));
    },

    send(msg) {
        if (this.isConnected && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(msg);
        } else {
            console.warn('[Upstream] 無法發送：尚未連線');
        }
    },

    async processMessage(messageStr) {
        let jsonObj;
        try {
            jsonObj = JSON.parse(messageStr);
        } catch(e) { return; }

        if (jsonObj.uuid && jsonObj.uuid.toString().startsWith("periodic_")) return;

        await MAIN.stateManager.addJson(messageStr);
        const action = jsonObj.action || "";
        const callerId = jsonObj.caller_id || "";

        if (!callerId) return;

        const msgDump = JSON.stringify(jsonObj);

        switch (action) {
            case "new_get_num":
            case "get_num_switch":
            case "cancel_get_num":
            case "reset_caller":
                await MAIN.stateManager.notifyClients(callerId, msgDump, 6); // 0x2 + 0x4
                break;
            case "reserve_number":
                await MAIN.stateManager.notifyClients(callerId, msgDump, 2);
                break;
            case "call_number":
                 await MAIN.stateManager.notifyClients(callerId, msgDump, 0xFF);
                 break;
        }
    }
};

MAIN.upstreamClient.connect();
console.log("-> 代理客戶端載入完成");
