// Drive slice 3b over XPC (sol-drive.md §2.1; ADR-041 amendment 2026-10-28).
// Who may send is XPC's job (code requirements on both ends); the agent core
// only parses the request strictly and hands it to the runner.
import Foundation
import XCTest
@testable import SolusInputCore

private final class Harness {
    let port = FakePort()
    lazy var agent = Agent(runner: Runner(port: port, unsignedDev: false))

    func send(_ line: String) -> [String: Any] { send(Data(line.utf8)) }

    func send(_ raw: Data) -> [String: Any] {
        let reply = agent.handle(raw)
        XCTAssertFalse(String(decoding: reply, as: UTF8.self).contains("\n"), "one JSON object")
        return (try? JSONSerialization.jsonObject(with: reply)) as? [String: Any] ?? [:]
    }

    func run(_ argv: [Any]) -> [String: Any] {
        send(Data(try! JSONSerialization.data(withJSONObject: ["v": 1, "id": 1, "op": "run", "argv": argv])))
    }
}

private let identify = ["identify", "--within", "/work"]

final class AgentRunTests: XCTestCase {
    func testRunHandsArgvToTheRunner() {
        let r = Harness().run(identify)
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual((r["front"] as? [String: Any])?["drivable"] as? Bool, true)
        XCTAssertEqual(r["unsignedDev"] as? Bool, false)
    }

    func testTheRunnersOwnChecksStillApply() {
        let h = Harness()
        XCTAssertEqual(h.run(["identify"])["ok"] as? Bool, true, "--within is optional (§2.2)")
        XCTAssertEqual(code(h.run(["capture", "--bundle", "org.kicad.kicad", "--window", "7"])), "usage",
                       "KiCad without --within")
        XCTAssertEqual(code(h.run(["identify", "--within", "/Users"])), "usage", "home ancestor")
        let act = ["act", "--bundle", "org.kicad.kicad", "--window", "7", "--since", "990",
                   "click", "--x", "10", "--y", "40", "--within", "/work"]
        XCTAssertEqual(h.run(act)["ok"] as? Bool, true)
        XCTAssertEqual(h.port.posted.count, 3)
    }

    func testOnlyIdentifyCaptureAndActRun() {
        let h = Harness()
        for argv in [["trust"], ["trust", "--prompt"], ["serve"], [], ["launch"], ["Identify"]] {
            XCTAssertEqual(code(h.run(argv)), "usage", argv.joined(separator: " "))
        }
        XCTAssertEqual(h.port.trustPrompts, 0)
    }

    func testArgvMustBeABoundedListOfStrings() {
        let h = Harness()
        XCTAssertEqual(code(h.run(["identify", 1])), "usage")
        XCTAssertEqual(code(h.run(["identify"] + Array(repeating: "x", count: 64))), "usage")
        for line in [#"{"v":1,"id":1,"op":"run","argv":"identify"}"#, #"{"v":1,"id":1,"op":"run"}"#,
                     #"{"v":1,"id":1,"op":"run","argv":null}"#] {
            XCTAssertEqual(code(h.send(line)), "usage", line)
        }
    }
}

final class AgentTrustTests: XCTestCase {
    func testTrustReportsAndMayPrompt() {
        let h = Harness()
        let r = h.send(#"{"v":1,"id":1,"op":"trust","prompt":false}"#)
        XCTAssertEqual(r["trust"] as? [String: Bool], ["accessibility": true, "screenRecording": true])
        XCTAssertEqual(r["unsignedDev"] as? Bool, false)
        XCTAssertEqual(h.port.trustPrompts, 0)
        XCTAssertEqual(h.send(#"{"v":1,"id":1,"op":"trust","prompt":true}"#)["ok"] as? Bool, true)
        XCTAssertEqual(h.port.trustPrompts, 1)
    }

    func testPromptMustBeABoolean() {
        let h = Harness()
        for line in [#"{"v":1,"id":1,"op":"trust"}"#, #"{"v":1,"id":1,"op":"trust","prompt":1}"#,
                     #"{"v":1,"id":1,"op":"trust","prompt":"yes"}"#, #"{"v":1,"id":1,"op":"trust","prompt":null}"#] {
            XCTAssertEqual(code(h.send(line)), "usage", line)
        }
        XCTAssertEqual(h.port.trustPrompts, 0)
    }
}

final class AgentRequestTests: XCTestCase {
    func testMalformedRequestsAreUsage() {
        let h = Harness()
        for line in ["", "garbage", "[]", "null", #""run""#, "{}",
                     #"{"v":2,"op":"trust","prompt":false}"#, #"{"v":"1","op":"trust","prompt":false}"#,
                     #"{"v":true,"op":"trust","prompt":false}"#, #"{"v":1.5,"op":"trust","prompt":false}"#,
                     #"{"op":"trust","prompt":false}"#, #"{"v":1}"#, #"{"v":1,"id":1,"op":"session"}"#,
                     #"{"v":1,"id":1,"op":"identify"}"#, #"{"v":1,"id":1,"op":"trust","prompt":false,"extra":0}"#,
                     #"{"v":1,"id":1,"op":"run","argv":["identify"],"token":"x"}"#, #"{"v":1,"id":1,"op":"TRUST","prompt":false}"#,
                     #"{"v":1,"id":1,"op":1}"#] {
            XCTAssertEqual(code(h.send(line)), "usage", line)
        }
        XCTAssertEqual(h.port.trustPrompts, 0)
        XCTAssertTrue(h.port.posted.isEmpty)
    }

    func testEveryRequestCarriesAPositiveIntegerId() {
        let h = Harness()
        for id in ["0", "-1", "1.5", #""1""#, "true", "null", "9007199254740993"] {
            let line = #"{"v":1,"id":\#(id),"op":"trust","prompt":false}"#
            XCTAssertEqual(code(h.send(line)), "usage", line)
        }
        XCTAssertEqual(code(h.send(#"{"v":1,"op":"trust","prompt":false}"#)), "usage", "no id")
        XCTAssertEqual(h.send(#"{"v":1,"id":9007199254740991,"op":"trust","prompt":false}"#)["ok"] as? Bool, true)
    }

    func testTheIdIsReadForTheServiceAndNothingElse() {
        XCTAssertEqual(Agent.requestId(Data(#"{"v":1,"id":42,"op":"trust","prompt":false}"#.utf8)), 42)
        XCTAssertEqual(Agent.requestId(Data(#"{"v":1,"id":7,"op":"run","argv":["identify"]}"#.utf8)), 7)
        XCTAssertNil(Agent.requestId(Data(#"{"v":1,"id":7,"op":"nope"}"#.utf8)), "only a valid request has an id")
        XCTAssertNil(Agent.requestId(Data("garbage".utf8)))
    }

    func testNotUTF8IsUsage() {
        XCTAssertEqual(code(Harness().send(Data([0xFF, 0xFE]))), "usage")
    }

    func testRequestsUpTo64KiBAreReadAndLongerOnesRefused() {
        let h = Harness()
        let body = #"{"v":1,"id":1,"op":"trust","prompt":false}"#
        let fits = body + String(repeating: " ", count: Agent.maxRequestBytes - body.utf8.count)
        XCTAssertEqual(Agent.maxRequestBytes, 65_536)
        XCTAssertEqual(h.send(fits)["ok"] as? Bool, true)
        XCTAssertEqual(code(h.send(fits + " ")), "usage")
    }

    func testATrailingNewlineIsAllowedButNotASecondObject() {
        let h = Harness()
        XCTAssertEqual(h.send("{\"v\":1,\"id\":1,\"op\":\"trust\",\"prompt\":false}\n")["ok"] as? Bool, true)
        XCTAssertEqual(code(h.send("{\"v\":1,\"id\":1,\"op\":\"trust\",\"prompt\":false}\n{}")), "usage")
    }
}

final class AgentStartTests: XCTestCase {
    func testTheAgentStartsOnlyWhenItsOwnCodeIsTheSignedHelper() {
        let team = "ABCDE12345"
        let port = FakePort()
        XCTAssertFalse(Agent.startAllowed(teamId: team, unsignedDev: false, port: port))
        port.ownRequirements = [Signing.requirement(teamId: team, identifier: Signing.helperIdentifier)]
        XCTAssertTrue(Agent.startAllowed(teamId: team, unsignedDev: false, port: port))
        port.ownRequirements.insert(Signing.requirement(teamId: Signing.teamIdPlaceholder, identifier: Signing.helperIdentifier))
        XCTAssertFalse(Agent.startAllowed(teamId: Signing.teamIdPlaceholder, unsignedDev: false, port: port))
        XCTAssertTrue(Agent.startAllowed(teamId: Signing.teamIdPlaceholder, unsignedDev: true, port: FakePort()))
    }

    func testTheListenerAdmitsOnlyAHardenedCurrentSolusApp() {
        XCTAssertEqual(Signing.appVersionFloor, "1.0.0")
        XCTAssertEqual(
            Signing.listenerRequirement(teamId: "ABCDE12345"),
            Signing.requirement(teamId: "ABCDE12345", identifier: "com.solusforge.solus")
                + #" and !(entitlement["com.apple.security.cs.allow-dyld-environment-variables"] exists)"#
                + #" and !(entitlement["com.apple.security.cs.disable-library-validation"] exists)"#
                + #" and !(entitlement["com.apple.security.get-task-allow"] exists)"#
                + #" and !(entitlement["com.apple.security.cs.allow-unsigned-executable-memory"] exists)"#
                + #" and !(entitlement["com.apple.security.cs.disable-executable-page-protection"] exists)"#
                + #" and info[CFBundleVersion] >= "1.0.0""#)
        XCTAssertNil(Signing.listenerRequirement(teamId: Signing.teamIdPlaceholder), "placeholder admits nobody")
        XCTAssertEqual(Signing.agentServiceName, "com.solusforge.solus.input.agent")
    }
}

/// The idle exit (60 s, §2.1): only when nothing is running or queued.
final class IdlePolicyTests: XCTestCase {
    func testExitsAfterSixtyQuietSecondsOnly() {
        XCTAssertEqual(IdlePolicy.timeoutSeconds, 60)
        XCTAssertFalse(IdlePolicy.shouldExit(now: 159, lastActivity: 100, pending: 0))
        XCTAssertTrue(IdlePolicy.shouldExit(now: 160, lastActivity: 100, pending: 0))
        XCTAssertFalse(IdlePolicy.shouldExit(now: 1_000, lastActivity: 100, pending: 1), "a run in progress")
    }
}

/// cancel(), invalidation and SIGTERM all reach the runner through one stop signal.
final class StopSignalTests: XCTestCase {
    func testCancelStopsOnlyTheRunningRequestOfThatConnection() {
        let stop = StopSignal()
        let a = NSObject(), b = NSObject()
        XCTAssertFalse(stop.isRaised)
        stop.cancel(a)
        XCTAssertTrue(stop.begin(a))
        XCTAssertFalse(stop.isRaised, "a cancel with nothing running does not poison the next request")
        stop.cancel(b)
        XCTAssertFalse(stop.isRaised, "another connection cannot stop it")
        stop.cancel(a)
        XCTAssertTrue(stop.isRaised)
        stop.end()
        XCTAssertTrue(stop.begin(a))
        XCTAssertFalse(stop.isRaised, "each request starts clear")
    }

    func testTerminationStopsTheRunAndRefusesNewOnes() {
        let stop = StopSignal()
        let a = NSObject()
        XCTAssertTrue(stop.begin(a))
        XCTAssertFalse(stop.terminate(), "busy: exit after the run")
        XCTAssertTrue(stop.isRaised)
        stop.end()
        XCTAssertFalse(stop.begin(a))
        XCTAssertTrue(StopSignal().terminate(), "idle: exit now")
    }

    func testARaiseWithoutAConnectionIsTheArgvModeSigterm() {
        let stop = StopSignal()
        stop.raise()
        XCTAssertTrue(stop.isRaised)
    }
}
