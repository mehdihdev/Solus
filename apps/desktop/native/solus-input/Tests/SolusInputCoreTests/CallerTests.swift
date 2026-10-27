// Drive slice 3 (sol-drive.md §2, §5; ADR-041 amendment 2026-10-27): the caller
// check, the `trust` command, `bounds` in replies, and the launcher's sibling path.
import Foundation
import XCTest
@testable import SolusInputCore

private let commands: [[String]] = [
    ["identify"],
    ["capture", "--bundle", "org.kicad.kicad", "--window", "7"],
    ["act", "--bundle", "org.kicad.kicad", "--window", "7", "--since", "990", "click", "--x", "10", "--y", "40"],
]

private func assertUntrusted(_ port: FakePort, caller: CallerPolicy = trustedCaller,
                             file: StaticString = #filePath, line: UInt = #line) {
    for argv in commands {
        let r = invoke(port, argv, caller: caller)
        XCTAssertEqual(code(r), "caller_untrusted", argv[0], file: file, line: line)
        XCTAssertEqual(r["message"] as? String, Runner.callerUntrustedMessage, file: file, line: line)
        XCTAssertNil(r["png"], file: file, line: line)
        XCTAssertNil(r["app"], "nothing read before the caller check", file: file, line: line)
    }
    XCTAssertTrue(port.posted.isEmpty, "nothing posted", file: file, line: line)
}

final class CallerCheckTests: XCTestCase {
    func testTheSignedCompanionUnderSolusIsTrusted() {
        let port = FakePort()
        for argv in commands {
            XCTAssertEqual(invoke(port, argv)["ok"] as? Bool, true, argv[0])
        }
        XCTAssertEqual(invoke(port, ["identify"])["unsignedDev"] as? Bool, false)
    }

    func testTheRequirementPinsAppleAnchorTeamAndIdentifier() {
        XCTAssertEqual(
            Signing.requirement(teamId: "ABCDE12345", identifier: "com.solusforge.solus.companion"),
            #"anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = "ABCDE12345" and identifier "com.solusforge.solus.companion""#)
        XCTAssertEqual(Signing.companionIdentifier, "com.solusforge.solus.companion")
        XCTAssertEqual(Signing.helperIdentifier, "com.solusforge.solus.input")
        XCTAssertEqual(Signing.appIdentifier, "com.solusforge.solus")
    }

    func testAParentThatIsNotTheCompanionIsRefused() {
        let port = FakePort()
        port.signedAs[500] = "com.solusforge.solus.mcp"
        assertUntrusted(port)
    }

    func testAnUnsignedParentIsRefused() {
        let port = FakePort()
        port.signedAs[500] = nil
        assertUntrusted(port)
    }

    func testAnotherTeamsSignatureIsRefused() {
        let port = FakePort()
        port.signedTeam = "ZZZZZ99999"
        assertUntrusted(port)
    }

    func testACompanionRunningAServerOrCommandIsRefused() {
        for count in [2, 5, 0] {
            let port = FakePort()
            port.argc[500] = count
            assertUntrusted(port)
        }
    }

    func testUnreadableArgumentsAreRefused() {
        let port = FakePort()
        port.argc = [:]
        assertUntrusted(port)
    }

    func testAGrandparentThatIsNotSolusIsRefused() {
        let port = FakePort()
        port.signedAs[400] = "com.apple.Terminal"
        assertUntrusted(port)
    }

    func testAnUnreadableGrandparentIsRefused() {
        let port = FakePort()
        port.parents = [:]
        assertUntrusted(port)
    }

    func testAnOrphanedHelperIsRefused() {
        for parent in [1, 0] {
            let port = FakePort()
            port.ownParent = parent
            port.signedAs[parent] = Signing.companionIdentifier
            port.parents[parent] = 400
            port.argc[parent] = 1
            assertUntrusted(port)
        }
    }

    func testAnInvalidOwnSignatureIsRefused() {
        let port = FakePort()
        port.selfValid = false
        assertUntrusted(port)
    }

    func testTheHelperMustBeSignedAsItselfByTheTeam() {
        // The helper's own requirement is pinned: valid but signed as something else fails.
        let port = FakePort()
        port.selfSignedAs = "com.solusforge.solus.companion"
        assertUntrusted(port)
    }

    /// Residual pending ADR decision (security review C1): the port reads identity
    /// by pid, so a parent that keeps its pid but exec()s into a different (still
    /// validly signed Solus) program between our checks is indistinguishable here.
    /// This test pins today's behaviour — it is ADMITTED — so a fix shows up as a
    /// deliberate change to this test, not a silent one.
    func testResidualAParentThatExecsAtTheSamePidIsIndistinguishable() {
        let port = FakePort()
        var execed = false
        port.afterSatisfies = { p in
            guard !execed else { return }
            execed = true
            p.argc[500] = 1 // the "new" program also takes no arguments; same pid, same ppid
        }
        XCTAssertEqual(invoke(port, ["identify"])["ok"] as? Bool, true, "residual C1: admitted")
    }

    func testTheParentDyingDuringTheCheckIsRefused() {
        // A dead parent's pid could be reused; the helper is re-parented to launchd.
        let port = FakePort()
        port.afterSatisfies = { $0.ownParent = 1 }
        assertUntrusted(port)
    }

    func testTheGrandparentDyingDuringTheCheckIsRefused() {
        let port = FakePort()
        port.afterSatisfies = { $0.parents[500] = 1 }
        assertUntrusted(port)
    }

    func testThePlaceholderTeamIdRefusesEveryCall() {
        let port = FakePort()
        port.signedTeam = Signing.teamIdPlaceholder // even a chain "signed" with it
        assertUntrusted(port, caller: CallerPolicy(teamId: Signing.teamIdPlaceholder))
    }

    func testAMalformedTeamIdRefusesEveryCall() {
        for team in ["", "abcde12345", "ABCDE1234", #"ABCDE"12345"#] {
            let port = FakePort()
            port.signedTeam = team
            assertUntrusted(port, caller: CallerPolicy(teamId: team))
        }
    }

    func testTheCallerCheckRunsBeforeArgumentChecks() {
        let port = FakePort()
        port.selfValid = false
        XCTAssertEqual(code(invoke(port, ["identify", "--x", "1"])), "caller_untrusted")
        XCTAssertEqual(code(invoke(port, ["act"], within: nil)), "caller_untrusted")
    }

    func testUnsignedDevModeSkipsTheCheckAndSaysSo() {
        let port = FakePort()
        port.signedAs = [:]
        port.selfValid = false
        let dev = CallerPolicy.unsignedDevelopment
        let r = invoke(port, ["identify"], caller: dev)
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["unsignedDev"] as? Bool, true)
        XCTAssertEqual(invoke(port, commands[1], caller: dev)["ok"] as? Bool, true)
        XCTAssertEqual(invoke(port, commands[2], caller: dev)["ok"] as? Bool, true)
    }
}

final class TrustCommandTests: XCTestCase {
    private func trust(_ port: FakePort, _ argv: [String], caller: CallerPolicy = trustedCaller) -> [String: Any] {
        invoke(port, argv, within: nil, caller: caller)
    }

    func testReportsBothGrantsWithoutTheCallerCheck() {
        let port = FakePort()
        port.selfValid = false // trust posts and captures nothing, so it skips the caller check
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
        XCTAssertEqual(trust(FakePort(), ["trust"], caller: .unsignedDevelopment)["unsignedDev"] as? Bool, true)
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
        port.windows = [:]
        let r = act(port, ["wait", "--ms", "1"])
        XCTAssertEqual(r["bounds"] as? [String: Int], ["x": 100, "y": 50, "width": 800, "height": 600])
    }
}

final class LauncherPathTests: XCTestCase {
    func testTheHelperRunsWithAFixedMinimalEnvironment() {
        // Nothing from the caller's environment (DYLD_*, SOLUS_*, …) reaches the helper.
        XCTAssertEqual(Launcher.environment, ["PATH=/usr/bin:/bin"])
    }

    func testTheSiblingIsTheHelperInTheSameDirectory() {
        XCTAssertEqual(Launcher.sibling(of: "/Applications/Solus.app/Contents/Resources/SolusInput.app/Contents/MacOS/solus-input-launch"),
                       "/Applications/Solus.app/Contents/Resources/SolusInput.app/Contents/MacOS/solus-input")
        XCTAssertEqual(Launcher.sibling(of: "/x/solus-input-launch"), "/x/solus-input")
    }

    func testOnlyAnAbsoluteResolvedPathHasASibling() {
        for path in ["", "solus-input-launch", "/", "relative/solus-input-launch", "/x/../y/solus-input-launch",
                     "/x/./solus-input-launch", "/x//solus-input-launch", "/x/solus-input-launch/"] {
            XCTAssertNil(Launcher.sibling(of: path), path)
        }
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
