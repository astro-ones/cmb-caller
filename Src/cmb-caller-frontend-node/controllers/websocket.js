// controllers/websocket.js
exports.install = function() {
    ROUTE('SOCKET /', wsHandler);
};

function wsHandler($) {
    $.on('open', function(client) {
        console.log(`[WS] Client 建立連線: ${client.id}`);
    });

    $.on('message', async function(client, msg) {
        const messageStr = msg.toString();
        let payload;
        try {
            payload = JSON.parse(messageStr);
            if (payload.action === 'auth' || payload.action === 'login') {
                const callerId = payload.caller_id || payload.caller;
                if(callerId){
                    client.custom.callerId = callerId;
                    client.custom.wsType = payload.ws_type || 0x1;
                    await MAIN.stateManager.addConnection(callerId, client.id, client, client.custom.wsType);
                }
            }
            if (MAIN.upstreamClient) {
                MAIN.upstreamClient.send(messageStr);
            }
        } catch(e) {
            // 例: CSV 解析
            if (MAIN.upstreamClient) {
                MAIN.upstreamClient.send(messageStr);
            }
        }
    });

    $.on('close', async function(client) {
        console.log(`[WS] Client 中斷連線: ${client.id}`);
        if (client.custom && client.custom.callerId) {
             await MAIN.stateManager.removeConnection(client.custom.callerId, client.id);
        }
    });
}
