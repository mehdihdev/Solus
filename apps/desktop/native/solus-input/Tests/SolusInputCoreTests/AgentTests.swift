// Drive slice 3b (sol-drive.md §2.1; ADR-041 amendments C1 and 3b): the agent
// authenticates every request — the socket peer's code identity AND, for `run`,
// the session token Solus.app was issued — before the runner sees it.
import Foundation
import XCTest
@testable import SolusInputCore

private let team = "ABCDE12345"
private let appRequirement = Signing.requirement(teamId: team, identifier: Signing.appIdentifier)
private let companionRequirement = Signing.requirement(teamId: team, identifier: Signing.companionIdentifier)

/// A peer that satisfies exactly one requirement (or none).
private func peer(_ requirement: String?) -> (String) -> Bool { { $0 == requirement } }
private let app = peer(appRequirement)
private let companion = peer(companionRequirement)

private final class Harness {
    let port = FakePort()
    var draws: [[UInt8]?] = [Array(0..<32), Array(repeating: 0xFF, count: 32)]
    lazy var agent = Agent(runner: Runner(port: port, unsignedDev: unsignedDev), teamId: teamId,
                           unsignedDev: unsignedDev, random: { [unowned self] count in
                               XCTAssertEqual(count, 32)
                               return self.draws.isEmpty ? nil : self.draws.removeFirst()
                           })
    let teamId: String
    let unsignedDev: Bool
    init(teamId: String = team, unsignedDev: Bool = false) { self.teamId = teamId; self.unsignedDev = unsignedDev }

    func send(_ line: String, _ from: (String) -> Bool) -> [String: Any] {
        send(Data((line + "\n").utf8), from)
    }

    func send(_ raw: Data, _ from: (String) -> Bool) -> [String: Any] {
        let reply = agent.handle(raw, peerSatisfies: from)
        XCTAssertFalse(reply.contains("\n"), "one JSON line")
        return (try? JSONSerialization.jsonObject(with: Data(reply.utf8))) as? [String: Any] ?? [:]
    }

    func session(_ from: (String) -> Bool = app) -> String? {
        send(#"{"v":1,"op":"session"}"#, from)["token"] as? String
    }

    func run(_ token: String?, _ argv: [String] = ["identify", "--within", "/work"],
             _ from: (String) -> Bool = companion) -> [String: Any] {
        var body: [String: Any] = ["v": 1, "op": "run", "argv": argv]
        if let token { body["token"] = token }
        let data = try! JSONSerialization.data(withJSONObject: body)
        return send(String(decoding: data, as: UTF8.self), from)
    }
}

private func base64url(_ bytes: [UInt8]) -> String {
    Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
}

final class AgentSessionTests: XCTestCase {
    func testSolusAppGetsA32ByteBase64urlToken() {
        let h = Harness()
        let token = h.session()
        XCTAssertEqual(token, base64url(Array(0..<32)))
        XCTAssertEqual(token?.count, 43)
        XCTAssertTrue(token?.allSatisfy { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" } ?? false)
    }

    func testACompanionCannotOpenASession() {
        let h = Harness()
        let r = h.send(#"{"v":1,"op":"session"}"#, companion)
        XCTAssertEqual(code(r), "caller_untrusted")
        XCTAssertNil(r["token"])
        XCTAssertEqual(h.draws.count, 2, "no token drawn")
    }

    func testAnUnsignedPeerCannotOpenASession() {
        XCTAssertEqual(code(Harness().send(#"{"v":1,"op":"session"}"#, peer(nil))), "caller_untrusted")
    }

    func testANewSessionSupersedesTheOldToken() {
        let h = Harness()
        let old = h.session()
        let new = h.session()
        XCTAssertNotEqual(old, new)
        XCTAssertEqual(code(h.run(old)), "bad_token")
        XCTAssertEqual(h.run(new)["ok"] as? Bool, true)
    }

    func testARandomFailureIssuesNothingAndRevokesTheOldToken() {
        let h = Harness()
        h.draws = [Array(0..<32), nil]
        let old = h.session()
        let r = h.send(#"{"v":1,"op":"session"}"#, app)
        XCTAssertEqual(r["ok"] as? Bool, false)
        XCTAssertNil(r["token"])
        XCTAssertEqual(code(h.run(old)), "bad_token")
    }

    func testAShortRandomDrawIsAFailure() {
        let h = Harness()
        h.draws = [Array(0..<31)]
        XCTAssertNil(h.session())
    }
}

final class AgentRunTests: XCTestCase {
    func testTheCompanionWithTheTokenReachesTheRunner() {
        let h = Harness()
        let r = h.run(h.session())
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["allowed"] as? Bool, true)
        XCTAssertEqual(r["unsignedDev"] as? Bool, false)
    }

    func testTheRunnersOwnRefusalsPassThrough() {
        let h = Harness()
        XCTAssertEqual(code(h.run(h.session(), ["identify"])), "usage", "no --within")
        let act = ["act", "--bundle", "org.kicad.kicad", "--window", "7", "--since", "990",
                   "click", "--x", "10", "--y", "40", "--within", "/work"]
        XCTAssertEqual(h.run(h.session(), act)["ok"] as? Bool, true)
        XCTAssertEqual(h.port.posted.count, 3)
    }

    func testSolusAppCannotRun() {
        let h = Harness()
        let token = h.session()
        XCTAssertEqual(code(h.run(token, ["identify", "--within", "/work"], app)), "caller_untrusted")
        XCTAssertEqual(code(h.run(token, ["identify", "--within", "/work"], peer(nil))), "caller_untrusted")
    }

    func testTheCallerCheckComesBeforeTheToken() {
        let h = Harness()
        XCTAssertEqual(code(h.run("x", ["identify", "--within", "/work"], app)), "caller_untrusted")
    }

    func testMissingWrongOrNoSessionTokensAreRefused() {
        let h = Harness()
        XCTAssertEqual(code(h.run(base64url(Array(0..<32)))), "bad_token", "before any session")
        let token = h.session()!
        XCTAssertEqual(code(h.run(nil)), "bad_token", "missing")
        XCTAssertEqual(code(h.run("")), "bad_token")
        XCTAssertEqual(code(h.run(String(token.dropLast()))), "bad_token", "short")
        XCTAssertEqual(code(h.run(token + "A")), "bad_token", "long")
        XCTAssertEqual(code(h.run(String(token.dropLast()) + (token.last == "A" ? "B" : "A"))), "bad_token")
        XCTAssertEqual(h.run(token)["ok"] as? Bool, true)
    }

    func testOnlyIdentifyCaptureAndActRun() {
        let h = Harness()
        let token = h.session()
        for argv in [["trust"], ["trust", "--prompt"], ["serve"], [], ["launch"]] {
            XCTAssertEqual(code(h.run(token, argv)), "usage", argv.joined(separator: " "))
        }
        XCTAssertEqual(h.port.trustPrompts, 0)
    }

    func testArgvMustBeStrings() {
        let h = Harness()
        let token = h.session()!
        for line in [#"{"v":1,"op":"run","token":"\#(token)","argv":["identify",1]}"#,
                     #"{"v":1,"op":"run","token":"\#(token)","argv":"identify"}"#,
                     #"{"v":1,"op":"run","token":"\#(token)"}"#,
                     #"{"v":1,"op":"run","token":7,"argv":["identify"]}"#] {
            XCTAssertEqual(code(h.send(line, companion)), "usage", line)
        }
    }
}

final class AgentTrustTests: XCTestCase {
    func testSolusAppReadsTrustAndMayPrompt() {
        let h = Harness()
        let r = h.send(#"{"v":1,"op":"trust","prompt":false}"#, app)
        XCTAssertEqual(r["trust"] as? [String: Bool], ["accessibility": true, "screenRecording": true])
        XCTAssertEqual(r["unsignedDev"] as? Bool, false)
        XCTAssertEqual(h.port.trustPrompts, 0)
        XCTAssertEqual(h.send(#"{"v":1,"op":"trust","prompt":true}"#, app)["ok"] as? Bool, true)
        XCTAssertEqual(h.port.trustPrompts, 1)
    }

    func testTheCompanionCannotAskForTrust() {
        let h = Harness()
        XCTAssertEqual(code(h.send(#"{"v":1,"op":"trust","prompt":true}"#, companion)), "caller_untrusted")
        XCTAssertEqual(h.port.trustPrompts, 0)
    }

    func testPromptMustBeABoolean() {
        let h = Harness()
        for line in [#"{"v":1,"op":"trust"}"#, #"{"v":1,"op":"trust","prompt":1}"#, #"{"v":1,"op":"trust","prompt":"yes"}"#] {
            XCTAssertEqual(code(h.send(line, app)), "usage", line)
        }
    }
}

final class AgentRequestTests: XCTestCase {
    func testMalformedRequestsAreUsage() {
        let h = Harness()
        for line in ["", "garbage", "[]", "null", #""session""#, "{}",
                     #"{"v":2,"op":"session"}"#, #"{"v":"1","op":"session"}"#, #"{"v":true,"op":"session"}"#,
                     #"{"v":1.5,"op":"session"}"#, #"{"op":"session"}"#, #"{"v":1}"#, #"{"v":1,"op":"identify"}"#,
                     #"{"v":1,"op":"session","extra":0}"#, #"{"v":1,"op":"SESSION"}"#, #"{"v":1,"op":1}"#] {
            XCTAssertEqual(code(h.send(line, app)), "usage", line)
        }
        XCTAssertEqual(h.draws.count, 2, "nothing issued")
    }

    func testTheLineMustBeOneNewlineTerminatedLine() {
        let h = Harness()
        XCTAssertEqual(code(h.send(Data(#"{"v":1,"op":"session"}"#.utf8), app)), "usage", "no newline")
        XCTAssertEqual(code(h.send(Data("{\"v\":1,\"op\":\"session\"}\n{}\n".utf8), app)), "usage", "two lines")
        XCTAssertEqual(code(h.send(Data([0xFF, 0xFE, 0x0A]), app)), "usage", "not UTF-8")
    }

    func testLinesUpTo64KiBAreReadAndLongerOnesRefused() {
        let h = Harness()
        let body = #"{"v":1,"op":"session"}"#
        let fits = body + String(repeating: " ", count: Agent.maxLineBytes - body.utf8.count)
        XCTAssertEqual(h.send(fits, app)["ok"] as? Bool, true)
        XCTAssertEqual(code(h.send(fits + " ", app)), "usage")
    }
}

final class AgentPolicyTests: XCTestCase {
    func testThePlaceholderTeamRefusesEveryPeer() {
        let h = Harness(teamId: Signing.teamIdPlaceholder)
        let anyone: (String) -> Bool = { _ in true }
        XCTAssertEqual(code(h.send(#"{"v":1,"op":"session"}"#, anyone)), "caller_untrusted")
        XCTAssertEqual(code(h.send(#"{"v":1,"op":"trust","prompt":false}"#, anyone)), "caller_untrusted")
        XCTAssertEqual(code(h.run("x", ["identify", "--within", "/work"], anyone)), "caller_untrusted")
    }

    func testUnsignedDevSkipsPeerChecksButNeverTheToken() {
        let h = Harness(teamId: Signing.teamIdPlaceholder, unsignedDev: true)
        let nobody = peer(nil)
        XCTAssertEqual(code(h.run(nil, ["identify", "--within", "/work"], nobody)), "bad_token")
        let token = h.session(nobody)
        XCTAssertEqual(code(h.run("wrong", ["identify", "--within", "/work"], nobody)), "bad_token")
        let r = h.run(token, ["identify", "--within", "/work"], nobody)
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["unsignedDev"] as? Bool, true)
    }

    func testTheAgentStartsOnlyWhenItsOwnCodeIsTheSignedHelper() {
        let port = FakePort()
        XCTAssertFalse(Agent.startAllowed(teamId: team, unsignedDev: false, port: port))
        port.ownRequirements = [Signing.requirement(teamId: team, identifier: Signing.helperIdentifier)]
        XCTAssertTrue(Agent.startAllowed(teamId: team, unsignedDev: false, port: port))
        port.ownRequirements.insert(Signing.requirement(teamId: Signing.teamIdPlaceholder, identifier: Signing.helperIdentifier))
        XCTAssertFalse(Agent.startAllowed(teamId: Signing.teamIdPlaceholder, unsignedDev: false, port: port))
        XCTAssertTrue(Agent.startAllowed(teamId: Signing.teamIdPlaceholder, unsignedDev: true, port: FakePort()))
    }
}

final class ServeOptionsTests: XCTestCase {
    func testReleaseAcceptsOnlyBareServe() {
        XCTAssertEqual(ServeOptions.parse(["serve"], unsignedDev: false), ServeOptions(socketDir: nil))
        XCTAssertNil(ServeOptions.parse(["serve", "--socket-dir", "/tmp/x"], unsignedDev: false))
        XCTAssertNil(ServeOptions.parse(["serve", "now"], unsignedDev: false))
        XCTAssertNil(ServeOptions.parse(["identify"], unsignedDev: false))
    }

    func testDebugMayNameAnAbsoluteSocketDirectory() {
        XCTAssertEqual(ServeOptions.parse(["serve", "--socket-dir", "/tmp/x"], unsignedDev: true),
                       ServeOptions(socketDir: "/tmp/x"))
        XCTAssertEqual(ServeOptions.parse(["serve"], unsignedDev: true), ServeOptions(socketDir: nil))
        for argv in [["serve", "--socket-dir"], ["serve", "--socket-dir", "rel"], ["serve", "--socket-dir", "/"],
                     ["serve", "--other", "/x"], ["serve", "--socket-dir", "/a", "--socket-dir", "/b"]] {
            XCTAssertNil(ServeOptions.parse(argv, unsignedDev: true), argv.joined(separator: " "))
        }
    }

    func testTheDefaultSocketLivesUnderApplicationSupport() {
        XCTAssertEqual(ServeOptions.defaultDirectory(home: "/Users/me"),
                       "/Users/me/Library/Application Support/Solus/drive")
        XCTAssertEqual(ServeOptions.socketName, "agent.sock")
    }
}

/// Cancellation (§2.1): the peer closing its end during a `run` stops the runner.
final class PeerClosedTests: XCTestCase {
    func testOpenQuietAndChattyPeersAreNotClosedButAHangUpIs() {
        var fds: [Int32] = [0, 0]
        XCTAssertEqual(socketpair(AF_UNIX, SOCK_STREAM, 0, &fds), 0)
        defer { close(fds[0]) }
        XCTAssertFalse(PeerWatch.hasClosed(fds[0]), "connected, nothing sent")
        var byte: UInt8 = 0x41
        XCTAssertEqual(send(fds[1], &byte, 1, 0), 1)
        XCTAssertFalse(PeerWatch.hasClosed(fds[0]), "extra bytes are not a hang-up")
        close(fds[1])
        XCTAssertTrue(PeerWatch.hasClosed(fds[0]), "the peer closed")
    }

    func testAnInvalidDescriptorCountsAsClosed() {
        XCTAssertTrue(PeerWatch.hasClosed(-1))
    }
}
