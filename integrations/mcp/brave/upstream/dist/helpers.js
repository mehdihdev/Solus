export function registerSigIntHandler(transports) {
    process.on('SIGINT', async () => {
        for (const sessionID of transports.keys()) {
            await transports.get(sessionID)?.close();
            transports.delete(sessionID);
        }
        console.error('Server shut down.');
        process.exit(0);
    });
}
