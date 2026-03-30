// definitions/state.js
// Manager for tracking WebSocket clients and caching JSON messages.

const MAX_JSON_CAPACITY = 20;
const JSON_TTL_SECONDS = 300;

MAIN.stateManager = {
    clients: new Map(), // caller_id -> client data
    jsonCache: [],
    
    // Future Redis integration placeholder
    // async initRedis() { ... }

    async updateCallerInfo(callerId, callerNum, callerName) {
        if (!this.clients.has(callerId)) return false;
        const entry = this.clients.get(callerId);
        if (callerNum !== undefined && !isNaN(callerNum)) {
            entry.callerNum = Number(callerNum);
        }
        if (callerName !== undefined) {
            entry.callerName = callerName;
        }
        return true;
    },

    async addConnection(callerId, clientId, ws, wsType) {
        if (!this.clients.has(callerId)) {
            let callerNum = 0; 
            this.clients.set(callerId, {
                connections: new Map(),
                callerNum: callerNum,
                callerName: '',
                connectTime: Date.now(),
                disconnectTime: null
            });
        }
        const entry = this.clients.get(callerId);
        entry.connections.set(clientId, {
            wsType: wsType,
            lastModified: Date.now(),
            ws: ws
        });
        entry.disconnectTime = null;
    },

    async removeConnection(callerId, clientId) {
        if (this.clients.has(callerId)) {
            const entry = this.clients.get(callerId);
            entry.connections.delete(clientId);
            if (entry.connections.size === 0) {
                entry.disconnectTime = Date.now();
            }
        }
    },

    async notifyClients(callerId, messageStr, wsTypeEnable, bypassClientId = null) {
        if (!this.clients.has(callerId)) return 0;
        let count = 0;
        const entry = this.clients.get(callerId);
        
        for (const [clientId, info] of entry.connections.entries()) {
            if ((info.wsType & wsTypeEnable) && clientId !== bypassClientId) {
                try {
                    info.ws.send(messageStr);
                    count++;
                } catch (e) {
                    console.error("[StateManager] 發送失敗", e);
                }
            }
        }
        return count;
    },

    async getAllClientsStatus() {
        const result = {};
        for (const [callerId, entry] of this.clients.entries()) {
            result[callerId] = {
                caller_num: entry.callerNum,
                connections_count: entry.connections.size,
                connect_time: new Date(entry.connectTime).toISOString(),
                disconnect_time: entry.disconnectTime ? new Date(entry.disconnectTime).toISOString() : null
            };
        }
        return result;
    },

    async addJson(dataStr) {
        try {
            const parsed = JSON.parse(dataStr);
            parsed._timestamp = Date.now();
            const now = Date.now();
            this.jsonCache = this.jsonCache.filter(r => (now - r._timestamp) < JSON_TTL_SECONDS * 1000);
            this.jsonCache.push(parsed);

            if (this.jsonCache.length > MAX_JSON_CAPACITY) {
                this.jsonCache.sort((a, b) => a._timestamp - b._timestamp);
                this.jsonCache = this.jsonCache.slice(this.jsonCache.length - MAX_JSON_CAPACITY);
            }
        } catch(e) {}
    },

    getAllBackData() {
        return this.jsonCache;
    }
};
console.log("-> 狀態管理器載入完成");
