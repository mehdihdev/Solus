// The XPC listener glue (sol-drive.md §2.1). Each accepted connection exports
// one endpoint; requests from every connection run one at a time on a serial
// queue, off the connection's own queue so `cancel()` can arrive mid-run.
// `cancel()` and the connection's invalidation or interruption raise the stop
// signal for that connection's running request — the old SIGTERM path.
import Foundation
import SolusInputCore
import SolusInputShared

public final class AgentService: NSObject, NSXPCListenerDelegate {
    private let stop: StopSignal
    private let handler: (Data) -> Data
    private let work = DispatchQueue(label: "com.solusforge.solus.input.agent.work")
    private let lock = NSLock()
    private var queued = 0
    private var last = ProcessInfo.processInfo.systemUptime

    public init(stop: StopSignal, handler: @escaping (Data) -> Data) {
        self.stop = stop
        self.handler = handler
    }

    /// Requests queued or running.
    public var pending: Int { lock.lock(); defer { lock.unlock() }; return queued }
    public var lastActivity: Double { lock.lock(); defer { lock.unlock() }; return last }

    public func listener(_ listener: NSXPCListener, shouldAcceptNewConnection connection: NSXPCConnection) -> Bool {
        let endpoint = Endpoint(service: self)
        connection.exportedInterface = NSXPCInterface(with: SolusInputAgent.self)
        connection.exportedObject = endpoint
        connection.invalidationHandler = { [stop] in stop.cancel(endpoint) }
        connection.interruptionHandler = { [stop] in stop.cancel(endpoint) }
        touch(0)
        connection.resume()
        return true
    }

    fileprivate func enqueue(_ owner: Endpoint, _ request: Data, _ reply: @escaping (Data) -> Void) {
        touch(1)
        work.async { [self] in
            defer { touch(-1) }
            guard stop.begin(owner) else { return } // terminating: the agent exits
            let response = handler(request)
            stop.end()
            reply(response)
        }
    }

    fileprivate func cancel(_ owner: Endpoint) { stop.cancel(owner) }

    private func touch(_ delta: Int) {
        lock.lock()
        queued += delta
        last = ProcessInfo.processInfo.systemUptime
        lock.unlock()
    }
}

private final class Endpoint: NSObject, SolusInputAgent {
    private weak var service: AgentService?

    init(service: AgentService) { self.service = service }

    func handle(_ request: Data, reply: @escaping (Data) -> Void) { service?.enqueue(self, request, reply) }
    func cancel() { service?.cancel(self) }
}

/// The release Mach-service listener: every connection must satisfy Solus.app's
/// requirement (checked by XPC on each message's send-time audit token).
public enum AgentListener {
    public static func machService(requirement: String) -> NSXPCListener {
        let listener = NSXPCListener(machServiceName: Signing.agentServiceName)
        listener.setConnectionCodeSigningRequirement(requirement)
        return listener
    }
}
