// The XPC listener glue (sol-drive.md §2.1). Each accepted connection exports
// one endpoint; requests from every connection run one at a time on a serial
// queue, off the connection's own queue so `cancel(id)` can arrive mid-run.
// `cancel(id)` stops that request if it is running (the old SIGTERM path, via
// the stop signal) or drops it with a `stopped` reply if it is still queued,
// and does nothing for any other id. The connection's invalidation or
// interruption does the same for every request it sent.
import Foundation
import SolusInputCore
import SolusInputShared

/// One request: who sent it, its id (nil when malformed — not cancellable), and
/// where its reply goes. Its identity is the stop signal's owner while it runs.
private final class Item {
    let sender: Endpoint
    let id: Int?
    let request: Data
    let reply: (Data) -> Void

    init(sender: Endpoint, id: Int?, request: Data, reply: @escaping (Data) -> Void) {
        self.sender = sender; self.id = id; self.request = request; self.reply = reply
    }
}

public final class AgentService: NSObject, NSXPCListenerDelegate {
    private let stop: StopSignal
    private let handler: (Data) -> Data
    private let onDrained: () -> Void
    private let work = DispatchQueue(label: "com.solusforge.solus.input.agent.work")
    private let lock = NSLock()
    private var queue: [Item] = []
    private var running: Item?
    private var last = ProcessInfo.processInfo.systemUptime

    /// `onDrainedWhileTerminating` runs when the last request finishes after `terminate()`.
    public init(stop: StopSignal, handler: @escaping (Data) -> Data,
                onDrainedWhileTerminating: @escaping () -> Void = { exit(0) }) {
        self.stop = stop
        self.handler = handler
        onDrained = onDrainedWhileTerminating
    }

    /// Requests queued or running.
    public var pending: Int { lock.lock(); defer { lock.unlock() }; return queue.count + (running == nil ? 0 : 1) }
    /// Updated only when a request arrives (a connection alone is not activity).
    public var lastActivity: Double { lock.lock(); defer { lock.unlock() }; return last }

    /// SIGTERM: stop the running request and refuse the queued ones. True when
    /// nothing is pending, so the caller can exit now; otherwise the service exits when drained.
    public func terminate() -> Bool {
        _ = stop.terminate()
        lock.lock(); defer { lock.unlock() }
        return queue.isEmpty && running == nil
    }

    public func listener(_ listener: NSXPCListener, shouldAcceptNewConnection connection: NSXPCConnection) -> Bool {
        let endpoint = Endpoint(service: self)
        connection.exportedInterface = NSXPCInterface(with: SolusInputAgent.self)
        connection.exportedObject = endpoint
        connection.invalidationHandler = { [weak self] in self?.cancelAll(from: endpoint) }
        connection.interruptionHandler = { [weak self] in self?.cancelAll(from: endpoint) }
        connection.resume()
        return true
    }

    fileprivate func enqueue(_ sender: Endpoint, _ request: Data, _ reply: @escaping (Data) -> Void) {
        let item = Item(sender: sender, id: Agent.requestId(request), request: request, reply: reply)
        lock.lock()
        queue.append(item)
        last = ProcessInfo.processInfo.systemUptime
        lock.unlock()
        work.async { [self] in runNext(item) }
    }

    /// Runs `item` unless it was dropped while queued.
    private func runNext(_ item: Item) {
        lock.lock()
        guard let index = queue.firstIndex(where: { $0 === item }) else { lock.unlock(); return }
        queue.remove(at: index)
        running = item
        lock.unlock()
        if stop.begin(item) {
            let response = handler(item.request)
            stop.end()
            item.reply(response)
        } else {
            item.reply(Agent.stoppedReply("the drive agent is stopping"))
        }
        lock.lock()
        running = nil
        let drained = queue.isEmpty && stop.isTerminating
        lock.unlock()
        if drained { onDrained() }
    }

    fileprivate func cancel(_ id: Int, from sender: Endpoint) {
        cancel { $0.sender === sender && $0.id == id }
    }

    private func cancelAll(from sender: Endpoint) { cancel { $0.sender === sender } }

    /// Stops the running request if it matches; drops (and answers) queued ones that match.
    private func cancel(where matches: (Item) -> Bool) {
        lock.lock()
        let dropped = queue.filter(matches)
        queue.removeAll(where: matches)
        let current = running.flatMap { matches($0) ? $0 : nil }
        lock.unlock()
        if let current { stop.cancel(current) }
        for item in dropped { item.reply(Agent.stoppedReply("cancelled before it ran")) }
    }
}

private final class Endpoint: NSObject, SolusInputAgent {
    private weak var service: AgentService?

    init(service: AgentService) { self.service = service }

    func handle(_ request: Data, reply: @escaping (Data) -> Void) { service?.enqueue(self, request, reply) }
    func cancel(_ requestId: Int) { service?.cancel(requestId, from: self) }
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
