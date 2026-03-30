// index.js
require('total5');

console.log('============================ Start!!! ============================');
console.log('=== CMB Caller Frontend (Node.js / Total.js v5) 版本 ===');

const config = {
    port: process.env.PORT || 38000
};

F.config.port = config.port;

// 啟動 HTTP 伺服器 (包含 WebSocket 支援)
Total.http({ port: config.port });
