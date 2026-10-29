// The exported interface end to end, in-process, over an anonymous listener
// (unsigned, so no code requirement — the Mach-service listener sets one).
import Foundation
import SolusInputCore
import SolusInputShared
import XCTest
@testable import SolusInputXPC

final class XPCRoundTripTests: XCTestCase {
    private func connect(_ service: AgentService) -> (NSXPCListener, NSXPCConnection) {
        let listener = NSXPCListener.anonymous()
        listener.delegate = service
        listener.resume()
        let connection = NSXPCConnection(listenerEndpoint: listener.endpoint)
        connection.remoteObjectInterface = NSXPCInterface(with: SolusInputAgent.self)
        connection.resume()
        return (listener, connection)
    }

    private func proxy(_ connection: NSXPCConnection) -> SolusInputAgent {
        connection.remoteObjectProxyWithErrorHandler { XCTFail("xpc error: \($0)") } as! SolusInputAgent
    }

    func testARequestRoundTripsThroughTheExportedInterface() {
        let stop = StopSignal()
        let service = AgentService(stop: stop) { request in Data("echo:".utf8) + request }
        let (listener, connection) = connect(service)
        defer { connection.invalidate(); listener.invalidate() }
        let replied = expectation(description: "reply")
        proxy(connection).handle(Data("{}".utf8)) { reply in
            XCTAssertEqual(String(decoding: reply, as: UTF8.self), "echo:{}")
            replied.fulfill()
        }
        wait(for: [replied], timeout: 5)
    }

    func testCancelReachesTheStopSignalOfTheRunningRequest() {
        let stop = StopSignal()
        let started = expectation(description: "started")
        let stopped = expectation(description: "stopped")
        let service = AgentService(stop: stop) { _ in
            started.fulfill()
            let deadline = Date().addingTimeInterval(5)
            while !stop.isRaised, Date() < deadline { usleep(1_000) }
            return Data((stop.isRaised ? "stopped" : "timeout").utf8)
        }
        let (listener, connection) = connect(service)
        defer { connection.invalidate(); listener.invalidate() }
        let agent = proxy(connection)
        agent.handle(Data()) { reply in
            XCTAssertEqual(String(decoding: reply, as: UTF8.self), "stopped")
            stopped.fulfill()
        }
        wait(for: [started], timeout: 5)
        agent.cancel()
        wait(for: [stopped], timeout: 5)
    }

    func testInvalidatingTheConnectionStopsTheRun() {
        let stop = StopSignal()
        let started = expectation(description: "started")
        let finished = expectation(description: "finished")
        let service = AgentService(stop: stop) { _ in
            started.fulfill()
            let deadline = Date().addingTimeInterval(5)
            while !stop.isRaised, Date() < deadline { usleep(1_000) }
            XCTAssertTrue(stop.isRaised, "invalidation is the old SIGTERM")
            finished.fulfill()
            return Data()
        }
        let (listener, connection) = connect(service)
        defer { listener.invalidate() }
        let agent = connection.remoteObjectProxyWithErrorHandler { _ in } as! SolusInputAgent // invalidation errors are expected
        agent.handle(Data()) { _ in }
        wait(for: [started], timeout: 5)
        connection.invalidate()
        wait(for: [finished], timeout: 5)
    }

    func testRequestsRunOneAtATimeAndActivityIsTracked() {
        let stop = StopSignal()
        let lock = NSLock()
        var running = 0, maxRunning = 0
        let service = AgentService(stop: stop) { _ in
            lock.lock(); running += 1; maxRunning = max(maxRunning, running); lock.unlock()
            usleep(20_000)
            lock.lock(); running -= 1; lock.unlock()
            return Data()
        }
        let (listener, connection) = connect(service)
        defer { connection.invalidate(); listener.invalidate() }
        let done = (0..<4).map { expectation(description: "reply \($0)") }
        for e in done { proxy(connection).handle(Data()) { _ in e.fulfill() } }
        wait(for: done, timeout: 5)
        XCTAssertEqual(maxRunning, 1)
        XCTAssertEqual(service.pending, 0)
    }
}
