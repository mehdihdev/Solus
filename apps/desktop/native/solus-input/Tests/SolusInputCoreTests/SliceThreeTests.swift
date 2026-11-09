// Drive slice 3 (sol-drive.md §2; ADR-041 amendments 2026-10-27): the signing
// requirement, the `trust` command, `bounds` in replies, the workspace/home rule.
import Foundation
import XCTest
@testable import SolusInputCore

final class SigningTests: XCTestCase {
    func testTheRequirementPinsDeveloperIdTeamAndIdentifier() {
        XCTAssertEqual(
            Signing.requirement(teamId: "ABCDE12345", identifier: "com.solusforge.solus.companion"),
            #"anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = "ABCDE12345" and identifier "com.solusforge.solus.companion""#)
        XCTAssertEqual(Signing.appIdentifier, "com.solusforge.solus")
        XCTAssertEqual(Signing.helperIdentifier, "com.solusforge.solus.input")
        XCTAssertEqual(Signing.teamId, Signing.teamIdPlaceholder, "one constant, shared with the native module")
    }

    func testOnlyARealTeamIdIsAccepted() {
        XCTAssertTrue(Signing.isRealTeamId("ABCDE12345"))
        for team in [Signing.teamIdPlaceholder, "", "abcde12345", "ABCDE1234", "ABCDE123456", #"ABCDE"1234"#] {
            XCTAssertFalse(Signing.isRealTeamId(team), team)
        }
    }

    func testReleaseArgvAnswersUsageAndSaysItIsNotUnsignedDev() {
        let r = try? JSONSerialization.jsonObject(with: Data(Runner.agentOnlyUsage.utf8)) as? [String: Any]
        XCTAssertEqual(r?["code"] as? String, "usage")
        XCTAssertEqual(r?["unsignedDev"] as? Bool, false)
        XCTAssertFalse(Runner.agentOnlyUsage.contains("\n"))
    }
}

final class TrustCommandTests: XCTestCase {
    private func trust(_ port: FakePort, _ argv: [String], unsignedDev: Bool = false) -> [String: Any] {
        invoke(port, argv, within: nil, unsignedDev: unsignedDev)
    }

    func testReportsBothGrants() {
        let port = FakePort()
        port.trusted = false
        let r = trust(port, ["trust"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["trust"] as? [String: Bool], ["accessibility": false, "screenRecording": true])
        XCTAssertEqual(r["unsignedDev"] as? Bool, false)
        XCTAssertEqual(port.trustPrompts, 0)
        XCTAssertTrue(port.posted.isEmpty)
    }

    func testPromptAsksMacOSBeforeReporting() {
        let port = FakePort()
        XCTAssertEqual(trust(port, ["trust", "--prompt"])["ok"] as? Bool, true)
        XCTAssertEqual(port.trustPrompts, 1)
    }

    func testReportsUnsignedDevMode() {
        XCTAssertEqual(trust(FakePort(), ["trust"], unsignedDev: true)["unsignedDev"] as? Bool, true)
    }

    func testTakesNoOtherArguments() {
        let port = FakePort()
        for argv in [["trust", "--within", "/work"], ["trust", "--prompt", "yes"], ["trust", "now"],
                     ["trust", "--prompt", "--prompt"]] {
            XCTAssertEqual(code(trust(port, argv)), "usage", argv.joined(separator: " "))
        }
        XCTAssertEqual(port.trustPrompts, 0)
    }
}

final class BoundsTests: XCTestCase {
    func testActReportsTheWindowBoundsReReadAfterPosting() {
        let port = FakePort()
        port.afterPost = { p in
            p.windows[7] = WindowInfo(id: 7, title: "", bounds: Rect(x: 120.4, y: 60, width: 800, height: 600),
                                      ownerBundleId: "org.kicad.kicad", ownerPid: 42, onScreen: true)
        }
        let r = act(port, ["click", "--x", "10", "--y", "40"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["bounds"] as? [String: Int], ["x": 120, "y": 60, "width": 800, "height": 600])
    }

    func testActFallsBackToTheCheckedBoundsWhenTheWindowCannotBeReRead() {
        let port = FakePort()
        port.afterPost = { $0.windows = [:] } // checked before posting, gone after
        let r = act(port, ["wait", "--ms", "1"])
        XCTAssertEqual(r["bounds"] as? [String: Int], ["x": 100, "y": 50, "width": 800, "height": 600])
    }
}

// The workspace may never be the home directory or above it: a KiCad working
// anywhere in the user's files would then count as "inside".
final class WorkspaceHomeTests: XCTestCase {
    private let identify = ["identify"]

    func testHomeAndItsAncestorsAreRefused() {
        for within in ["/Users/me", "/Users", "/Users/me/"] {
            let port = FakePort()
            port.resolve = { $0.count > 1 && $0.hasSuffix("/") ? String($0.dropLast()) : $0 }
            XCTAssertEqual(code(invoke(port, identify, within: within)), "usage", within)
        }
    }

    func testHomeIsComparedResolved() {
        let port = FakePort()
        port.home = "/var/home-link"
        port.resolve = { $0 == "/var/home-link" ? "/Users/me" : $0 }
        XCTAssertEqual(code(invoke(port, identify, within: "/Users/me")), "usage")
        XCTAssertEqual(code(invoke(port, identify, within: "/Users")), "usage")
    }

    func testFoldersInsideHomeAndPrefixSiblingsAreFine() {
        let port = FakePort()
        port.cwd[42] = "/Users/me/board"
        XCTAssertEqual(invoke(port, identify, within: "/Users/me/board")["ok"] as? Bool, true)
        XCTAssertEqual(invoke(port, identify, within: "/Users/meadow")["ok"] as? Bool, true)
        XCTAssertEqual(invoke(port, identify, within: "/work")["ok"] as? Bool, true)
    }

    func testAnUnreadableHomeFailsClosed() {
        let port = FakePort()
        port.home = nil
        XCTAssertEqual(code(invoke(port, identify)), "usage")
        XCTAssertEqual(code(act(port, ["wait", "--ms", "1"])), "usage")
        XCTAssertTrue(port.posted.isEmpty)
    }
}
