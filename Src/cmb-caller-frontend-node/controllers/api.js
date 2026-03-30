// controllers/api.js
exports.install = function() {
    ROUTE('GET /', root);
    ROUTE('GET /health', healthCheck);
    ROUTE('GET /info', info);
    ROUTE('GET /status', info);
    ROUTE('GET /show_all_back_data', showAllBackData);
    ROUTE('GET /reboot', reboot);
    ROUTE('GET /restart', reboot);
};

function root() {
    this.json({ service: "cmb-caller-frontend", version: "Node Total.js" });
}

function healthCheck() {
    this.json({
        status: "healthy",
        active_connections: MAIN.stateManager.clients.size,
        timestamp: new Date().toISOString()
    });
}

async function info() {
    const clientsStatus = await MAIN.stateManager.getAllClientsStatus();
    this.json({
        service: "total.js cmb-caller-frontend",
        status: "running",
        connections: clientsStatus
    });
}

function showAllBackData() {
    this.json({ status: "OK", data: MAIN.stateManager.getAllBackData() });
}

function reboot() {
    this.json({ message: "Restarting..." });
    setTimeout(() => process.exit(1), 1000);
}
