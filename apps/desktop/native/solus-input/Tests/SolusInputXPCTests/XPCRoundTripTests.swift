// The exported interface end to end, in-process, over an anonymous listener
// (unsigned, so no code requirement — the Mach-service listener sets one).
import Foundation
import SolusInputCore
import SolusInputShared
import XCTest
@testable import SolusInputXPC

private func request(_ id: Int, _ op: String = "trust") -> Data {
    Data((op == "trust" ? #"{"v":1,"id":\#(id),"op":"trust","prompt":false}"#
        : #"{"v":1,"id":\#(id),"op":"run","argv":["identify"]}"#).utf8)
}

private func text(_ data: Data) -> String { String(decoding: data, as: UTF8.self) }

/// A handler that blocks run requests until released or stopped; trust replies at once.
private final class Gate: @unchecked Sendable {
    let stop: StopSignal
    let started = DispatchSemaphore(value: 0)
    private let release = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private(set) var handled: [Int] = []

    init(_ stop: StopSignal) { self.stop = stop }

    func open() { release.signal() }

    func handle(_ data: Data) -> Data {
        let id = Agent.requestId(data) ?? -1
        lock.lock(); handled.append(id); lock.unlock()
        guard text(data).contains(#""op":"run""#) else { return Data("done \(id)".utf8) }
        started.signal()
        let deadline = Date().addingTimeInterval(5)
        while !stop.isRaised, Date() < deadline, release.wait(timeout: .now() + .milliseconds(1)) == .timedOut {}
        return Data((stop.isRaised ? "stopped \(id)" : "done \(id)").utf8)
    }
}

final class XPCRoundTripTests: XCTestCase {
    private var listener: NSXPCListener!
    private var connection: NSXPCConnection!
    /// The listener's delegate is weak; the test owns the service, as main does.
    private var service: AgentService!

    private func connect(_ service: AgentService) -> SolusInputAgent {
        self.service = service
        listener = NSXPCListener.anonymous()
        listener.delegate = service
        listener.resume()
        connection = NSXPCConnection(listenerEndpoint: listener.endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: SolusInputAgent.self)
        connection.resume()
        return connection.remoteObjectProxyWithErrorHandler { _ in } as! SolusInputAgent
    }

    override func tearDown() {
        connection?.invalidate()
        listener?.invalidate()
    }

    private func send(_ agent: SolusInputAgent, _ data: Data, _ name: String) -> (XCTestExpectation, () -> String) {
        let done = expectation(description: name)
        let lock = NSLock()
        var reply = ""
        agent.handle(data) { r in lock.lock(); reply = text(r); lock.unlock(); done.fulfill() }
        return (done, { lock.lock(); defer { lock.unlock() }; return reply })
    }

    func testARequestRoundTripsThroughTheExportedInterface() {
        let service = AgentService(stop: StopSignal()) { Data("echo:".utf8) + $0 }
        let agent = connect(service)
        let (done, reply) = send(agent, request(1), "reply")
        wait(for: [done], timeout: 5)
        XCTAssertEqual(reply(), "echo:" + text(request(1)))
    }

    func testCancelStopsTheRunningRequestWithThatId() {
        let stop = StopSignal()
        let gate = Gate(stop)
        let agent = connect(AgentService(stop: stop, handler: gate.handle))
        let (done, reply) = send(agent, request(1, "run"), "run")
        XCTAssertEqual(gate.started.wait(timeout: .now() + 5), .success)
        agent.cancel(1)
        wait(for: [done], timeout: 5)
        XCTAssertEqual(reply(), "stopped 1")
    }

    func testATimedOutQueuedRequestDoesNotStopTheRunningOne() {
        let stop = StopSignal()
        let gate = Gate(stop)
        let agent = connect(AgentService(stop: stop, handler: gate.handle))
        let (run, runReply) = send(agent, request(1, "run"), "run")
        XCTAssertEqual(gate.started.wait(timeout: .now() + 5), .success)
        let (trust, trustReply) = send(agent, request(2), "trust")
        agent.cancel(2) // the trust request's deadline
        wait(for: [trust], timeout: 5)
        XCTAssertTrue(trustReply().contains(#""code":"stopped""#), trustReply())
        XCTAssertFalse(stop.isRaised, "the run is untouched")
        gate.open()
        wait(for: [run], timeout: 5)
        XCTAssertEqual(runReply(), "done 1")
        XCTAssertEqual(gate.handled, [1], "the dropped request never reached the handler")
    }

    func testAStaleCancelNeverHitsTheNextRequest() {
        let stop = StopSignal()
        let gate = Gate(stop)
        let agent = connect(AgentService(stop: stop, handler: gate.handle))
        let (first, _) = send(agent, request(1), "first")
        wait(for: [first], timeout: 5)
        agent.cancel(1) // arrives after request 1 finished
        agent.cancel(3) // never existed
        let (second, reply) = send(agent, request(2, "run"), "second")
        XCTAssertEqual(gate.started.wait(timeout: .now() + 5), .success)
        usleep(50_000)
        XCTAssertFalse(stop.isRaised)
        gate.open()
        wait(for: [second], timeout: 5)
        XCTAssertEqual(reply(), "done 2")
    }

    func testARequestWithoutAValidIdIsAnsweredButNotCancellable() {
        let service = AgentService(stop: StopSignal()) { _ in Data("handled".utf8) }
        let agent = connect(service)
        let (done, reply) = send(agent, Data("garbage".utf8), "garbage")
        wait(for: [done], timeout: 5)
        XCTAssertEqual(reply(), "handled", "the agent core answers usage for it")
    }

    func testInvalidatingTheConnectionStopsTheRun() {
        let stop = StopSignal()
        let gate = Gate(stop)
        let finished = expectation(description: "finished")
        let service = AgentService(stop: stop) { data in
            let out = gate.handle(data)
            XCTAssertEqual(text(out), "stopped 1", "invalidation is the old SIGTERM")
            finished.fulfill()
            return out
        }
        let agent = connect(service)
        agent.handle(request(1, "run")) { _ in }
        XCTAssertEqual(gate.started.wait(timeout: .now() + 5), .success)
        connection.invalidate()
        wait(for: [finished], timeout: 5)
    }

    func testRequestsRunOneAtATimeAndOnlyRequestsCountAsActivity() {
        let lock = NSLock()
        var running = 0, maxRunning = 0
        let service = AgentService(stop: StopSignal()) { _ in
            lock.lock(); running += 1; maxRunning = max(maxRunning, running); lock.unlock()
            usleep(20_000)
            lock.lock(); running -= 1; lock.unlock()
            return Data()
        }
        let before = service.lastActivity
        let agent = connect(service)
        usleep(20_000)
        XCTAssertEqual(service.lastActivity, before, "a connection alone is not activity")
        let done = (1...4).map { id in send(agent, request(id), "reply \(id)").0 }
        wait(for: done, timeout: 5)
        XCTAssertEqual(maxRunning, 1)
        XCTAssertEqual(service.pending, 0)
        XCTAssertGreaterThan(service.lastActivity, before)
    }

    func testAfterTerminationQueuedWorkIsRefusedAndTheServiceDrains() {
        let stop = StopSignal()
        let gate = Gate(stop)
        let drained = expectation(description: "drained")
        let service = AgentService(stop: stop, handler: gate.handle, onDrainedWhileTerminating: { drained.fulfill() })
        let agent = connect(service)
        let (run, runReply) = send(agent, request(1, "run"), "run")
        XCTAssertEqual(gate.started.wait(timeout: .now() + 5), .success)
        let (queued, queuedReply) = send(agent, request(2), "queued")
        usleep(20_000)
        XCTAssertFalse(service.terminate(), "busy: exit when drained")
        wait(for: [run, queued, drained], timeout: 5)
        XCTAssertEqual(runReply(), "stopped 1")
        XCTAssertTrue(queuedReply().contains(#""code":"stopped""#), queuedReply())
        XCTAssertEqual(gate.handled, [1])
    }

    func testTerminatingWhileIdleExitsAtOnce() {
        let service = AgentService(stop: StopSignal()) { $0 }
        XCTAssertTrue(service.terminate())
    }
}
