// ADR-041 §5 / sol-drive.md §2: every check happens before ANY event is posted,
// and a refusal posts nothing. Driven through `Runner` against a fake system.
import Foundation
import XCTest
@testable import SolusInputCore

final class FakePort: SystemPort {
    var trusted = true
    var screenRecording = true
    var front: FrontmostInfo?
    var windows: [UInt32: WindowInfo] = [:]
    /// nil = the focused element could not be read (counts as secure).
    var secure: Bool? = false
    var titleBar: Double = 28
    var stop = false
    var idle: Double = 100
    var clock: Double = 1_000
    var posted: [SyntheticEvent] = []
    var postedPids: [Int?] = []
    /// The topmost on-screen window at a global point; nil = the bound window (7).
    var windowAt: (Point) -> UInt32? = { _ in nil }
    /// Called after each post — lets a test change the world mid-verb.
    var afterPost: (FakePort) -> Void = { _ in }
    var image = CapturedImage(png: Data([0x89, 0x50]), imageWidth: 1568, imageHeight: 1176)
    /// Each process's working directory (already resolved); KiCad's is its project folder.
    var cwd: [Int: String] = [42: "/work/board"]
    /// `realpath` of a path the caller passes; nil = it does not resolve.
    var resolve: (String) -> String? = { $0 }
    /// What the helper's own code satisfies (the agent's start check).
    var ownRequirements: Set<String> = []
    var trustPrompts = 0
    /// The home directory from the user database (never $HOME); nil = unreadable.
    var home: String? = "/Users/me"
    static let team = "ABCDE12345"

    static let kicadWindow = WindowInfo(
        id: 7, title: "board — Schematic Editor",
        bounds: Rect(x: 100, y: 50, width: 800, height: 600),
        ownerBundleId: "org.kicad.kicad", ownerPid: 42, onScreen: true)

    init() {
        front = FrontmostInfo(
            app: AppInfo(bundleId: "org.kicad.kicad", pid: 42, name: "KiCad"),
            window: FakePort.kicadWindow)
        windows[7] = FakePort.kicadWindow
    }

    func accessibilityTrusted() -> Bool { trusted }
    func screenRecordingAllowed() -> Bool { screenRecording }
    func frontmost() -> FrontmostInfo? { front }
    func window(id: UInt32) -> WindowInfo? { windows[id] }
    func focusedElementIsSecure(pid: Int) -> Bool? { secure }
    func titleBarHeight(window: WindowInfo) -> Double { titleBar }
    func stopRequested() -> Bool { stop }
    func secondsSinceLastPhysicalInput() -> Double { idle }
    func now() -> Double { clock }
    func capture(window: WindowInfo, maxEdge: Int) throws -> CapturedImage { image }
    func topWindow(at point: Point) -> UInt32? { windowAt(point) ?? front?.window?.id }
    func workingDirectory(pid: Int) -> String? { cwd[pid] }
    func resolvedPath(_ path: String) -> String? { resolve(path) }
    func ownCodeSatisfies(requirement: String) -> Bool { ownRequirements.contains(requirement) }
    func homeDirectory() -> String? { home }
    func requestTrust() { trustPrompts += 1 }
    func post(_ event: SyntheticEvent, toPid pid: Int?) {
        posted.append(event)
        postedPids.append(pid)
        afterPost(self)
    }
}

/// Every command runs bound to the linked workspace `/work` unless a test says otherwise.
func invoke(_ port: FakePort, _ argv: [String], within: String? = "/work",
            unsignedDev: Bool = false) -> [String: Any] {
    let line = Runner(port: port, unsignedDev: unsignedDev).run(argv + (within.map { ["--within", $0] } ?? []))
    XCTAssertFalse(line.contains("\n"), "exactly one JSON line")
    let object = try? JSONSerialization.jsonObject(with: Data(line.utf8))
    return object as? [String: Any] ?? [:]
}

func act(_ port: FakePort, _ verb: [String], bundle: String = "org.kicad.kicad",
                 window: String = "7", since: String = "990") -> [String: Any] {
    invoke(port, ["act", "--bundle", bundle, "--window", window, "--since", since] + verb)
}

func code(_ result: [String: Any]) -> String? { result["code"] as? String }

final class IdentifyTests: XCTestCase {
    func testReportsTheFrontmostAppWindowTrustAndWhetherItIsDrivable() {
        let port = FakePort()
        let r = invoke(port, ["identify"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual((r["app"] as? [String: Any])?["bundleId"] as? String, "org.kicad.kicad")
        let window = r["window"] as? [String: Any]
        XCTAssertEqual(window?["id"] as? Int, 7)
        XCTAssertEqual((window?["bounds"] as? [String: Any])?["width"] as? Int, 800)
        XCTAssertEqual(r["allowed"] as? Bool, true)
        XCTAssertEqual((r["trust"] as? [String: Any])?["accessibility"] as? Bool, true)
    }

    func testAnotherAppIsReportedButNotAllowed() {
        let port = FakePort()
        port.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "Terminal"),
                                   window: nil)
        port.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.mail", pid: 9, name: "Mail"),
                                   window: WindowInfo(id: 3, title: "Re: salary review", bounds: Rect(x: 0, y: 0, width: 9, height: 9),
                                                      ownerBundleId: "com.apple.mail", ownerPid: 9, onScreen: true))
        let r = invoke(port, ["identify"])
        XCTAssertEqual(r["allowed"] as? Bool, false)
        XCTAssertTrue(r["window"] is NSNull, "never another app's window title")
        XCTAssertTrue(r["app"] is NSNull, "never another app's identity")
        XCTAssertNotNil(r["trust"])
    }
}

final class CaptureTests: XCTestCase {
    func testCapturesAnAllowlistedWindowWithBothSizes() {
        let r = invoke(FakePort(), ["capture", "--bundle", "org.kicad.kicad", "--window", "7"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["png"] as? String, Data([0x89, 0x50]).base64EncodedString())
        XCTAssertEqual(r["imageWidth"] as? Int, 1568)
        XCTAssertEqual(r["pointsWidth"] as? Int, 800)
        XCTAssertEqual(r["pointsHeight"] as? Int, 600)
        XCTAssertEqual(r["bounds"] as? [String: Int], ["x": 100, "y": 50, "width": 800, "height": 600])
    }

    func testRefusesAnAppOffTheDrivableList() {
        XCTAssertEqual(code(invoke(FakePort(), ["capture", "--bundle", "com.apple.Terminal", "--window", "7"])),
                       "app_not_allowed")
    }

    func testRefusesAMissingWindowOrOneOwnedByAnotherApp() {
        let port = FakePort()
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "8"])),
                       "window_not_found")
        port.windows[8] = WindowInfo(id: 8, title: "", bounds: Rect(x: 0, y: 0, width: 10, height: 10),
                                     ownerBundleId: "org.kicad.eeschema", ownerPid: 43, onScreen: true)
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "8"])),
                       "window_mismatch")
    }

    func testACaptureWhoseShapeDoesNotMatchTheWindowIsRefused() {
        let port = FakePort()
        port.image = CapturedImage(png: Data([1]), imageWidth: 1600, imageHeight: 1176) // shadow padding
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "7"])),
                       "capture_failed")
    }

    func testRefusesWithoutScreenRecording() {
        let port = FakePort()
        port.screenRecording = false
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "7"])),
                       "screen_recording_denied")
    }
}

final class ActGuardTests: XCTestCase {
    func testEveryGuardRefusesAndPostsNothing() {
        let cases: [(String, (FakePort) -> Void, [String], String)] = [
            ("untrusted", { $0.trusted = false }, ["click", "--x", "1", "--y", "40"], "not_trusted"),
            ("other app in front", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "T"),
                                         window: nil)
            }, ["click", "--x", "1", "--y", "40"], "not_frontmost"),
            ("other window in front", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: "org.kicad.kicad", pid: 42, name: "KiCad"),
                                         window: WindowInfo(id: 9, title: "x",
                                                            bounds: Rect(x: 0, y: 0, width: 50, height: 50),
                                                            ownerBundleId: "org.kicad.kicad", ownerPid: 42, onScreen: true))
            }, ["click", "--x", "1", "--y", "40"], "window_mismatch"),
            ("x past the edge", { _ in }, ["click", "--x", "800", "--y", "1"], "out_of_bounds"),
            ("negative y", { _ in }, ["move", "--x", "1", "--y", "-1"], "out_of_bounds"),
            ("drag end outside", { _ in },
             ["drag", "--x", "1", "--y", "40", "--to-x", "1", "--to-y", "600"], "out_of_bounds"),
            ("user moved", { $0.idle = 0.3 }, ["click", "--x", "1", "--y", "40"], "user_active"),
            ("another window on top", { p in p.windowAt = { _ in 99 } },
             ["click", "--x", "1", "--y", "40"], "occluded"),
            ("drag ends under another window", { p in
                p.windowAt = { $0.x > 150 ? 99 : nil }
            }, ["drag", "--x", "1", "--y", "40", "--to-x", "100", "--to-y", "40"], "occluded"),
            ("denied chord", { _ in }, ["key", "--chord", "cmd+q"], "chord_denied"),
            ("unknown key", { _ in }, ["key", "--chord", "cmd+banana"], "bad_chord"),
            ("password field", { $0.secure = true }, ["type", "--text", "hunter2"], "secure_field"),
            ("newline", { _ in }, ["type", "--text", "a\nb"], "bad_text"),
            ("too long", { _ in }, ["type", "--text", String(repeating: "a", count: 201)], "bad_text"),
            ("long wait", { _ in }, ["wait", "--ms", "2001"], "usage"),
        ]
        for (name, setup, verb, expected) in cases {
            let port = FakePort()
            setup(port)
            XCTAssertEqual(code(act(port, verb)), expected, name)
            XCTAssertEqual(port.posted, [], "\(name) must post nothing")
        }
    }

    func testSinceMustBeFiniteNotInTheFutureAndRecent() {
        for since in ["inf", "nan", "1001.5", "300"] { // clock is 1000; > 10 min old is stale
            let port = FakePort()
            XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "40"], since: since)), "usage", since)
            XCTAssertEqual(port.posted, [])
        }
    }

    func testFocusLostMidVerbStopsBeforeTheNextEvent() {
        let port = FakePort()
        port.afterPost = { p in
            p.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "T"), window: nil)
        }
        let r = act(port, ["click", "--x", "1", "--y", "40"])
        XCTAssertEqual(code(r), "focus_lost")
        XCTAssertEqual(r["postedEvents"] as? Int, 1)
        XCTAssertEqual(port.posted.count, 1, "nothing after the focus change")
    }

    func testAPopupAppearingMidDragStopsAndReleasesTheButtonToTheBoundAppOnly() {
        let port = FakePort()
        var posts = 0
        port.afterPost = { p in
            posts += 1
            if posts == 3 { p.windowAt = { _ in 99 } } // a menu opens after the first drag step
        }
        let r = act(port, ["drag", "--x", "1", "--y", "40", "--to-x", "100", "--to-y", "40"])
        XCTAssertEqual(code(r), "occluded")
        XCTAssertEqual(r["postedEvents"] as? Int, 3)
        guard case .mouseUp(.left, _, clicks: 1) = port.posted.last else { return XCTFail("button left held") }
        XCTAssertEqual(port.postedPids.last, 42, "the release goes to KiCad, never to the popup")
    }

    func testRightDoubleClickIsRefused() {
        let port = FakePort()
        XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "1", "--button", "right", "--count", "2"])),
                       "usage")
        XCTAssertEqual(port.posted, [])
    }

    func testTheTitleBarIsOffLimits() {
        let port = FakePort()
        XCTAssertEqual(code(act(port, ["click", "--x", "10", "--y", "10"])), "window_chrome")
        XCTAssertEqual(code(act(port, ["drag", "--x", "10", "--y", "40", "--to-x", "10", "--to-y", "5"])),
                       "window_chrome")
        XCTAssertEqual(port.posted, [])
    }

    func testPasswordFieldsAreProtectedFromKeysTooAndUnknownCountsAsSecure() {
        for (secure, verb) in [(Bool?.some(true), ["key", "--chord", "a"]),
                               (nil, ["type", "--text", "x"]), (nil, ["key", "--chord", "return"])] {
            let port = FakePort()
            port.secure = secure
            XCTAssertEqual(code(act(port, verb)), "secure_field", "\(verb)")
            XCTAssertEqual(port.posted, [])
        }
    }

    func testPhysicalInputMidVerbStopsAtTheNextEvent() {
        let port = FakePort()
        port.afterPost = { p in p.idle = 0 } // the user grabbed the mouse right after our first event
        port.clock = 1_000
        var tick = 1_000.0
        let original = port.afterPost
        port.afterPost = { p in original(p); tick += 0.2; p.clock = tick }
        let r = act(port, ["drag", "--x", "1", "--y", "40", "--to-x", "100", "--to-y", "40"])
        XCTAssertEqual(code(r), "user_active")
        XCTAssertEqual(r["postedEvents"] as? Int, 1)
    }

    func testAStopSignalEndsTheVerbAndReleasesAHeldButton() {
        let port = FakePort()
        var posts = 0
        port.afterPost = { p in posts += 1; if posts == 2 { p.stop = true } }
        let r = act(port, ["drag", "--x", "1", "--y", "40", "--to-x", "100", "--to-y", "40"])
        XCTAssertEqual(code(r), "stopped")
        XCTAssertEqual(r["postedEvents"] as? Int, 2)
        guard case .mouseUp(.left, let at, clicks: 1) = port.posted.last else { return XCTFail("button left held") }
        XCTAssertEqual(at, Point(x: 101, y: 90))
        XCTAssertEqual(port.postedPids.last, Optional<Int>.none, "still over the window: release globally")
    }

    func testAResizeSinceTheCaptureRefuses() {
        let port = FakePort()
        XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "40", "--expect-width", "640",
                                       "--expect-height", "600"])), "window_resized")
        XCTAssertEqual(act(port, ["click", "--x", "1", "--y", "40", "--expect-width", "800",
                                  "--expect-height", "600"])["ok"] as? Bool, true)
    }

    func testTypeRefusesInvisibleAndFunctionKeyCharacters() {
        for text in ["\u{F704}", "a\u{2028}b", "a\u{2029}", "a" + String(repeating: "\u{0301}", count: 300), "\u{200B}"] {
            let port = FakePort()
            XCTAssertEqual(code(act(port, ["type", "--text", text])), "bad_text", text.debugDescription)
        }
        let port = FakePort()
        XCTAssertEqual(act(port, ["type", "--text", "R1 = 10k Ω, 5%"])["ok"] as? Bool, true)
    }

    func testMalformedArgumentEdgeCases() {
        let port = FakePort()
        for argv in [
            ["act", "--bundle", "org.kicad.kicad", "--bundle", "x", "--window", "7", "--since", "990", "wait", "--ms", "1"],
            ["act", "--bundle", "org.kicad.kicad", "--window", "7", "--since", "990", "wait", "wait", "--ms", "1"],
            ["act", "--bundle", "org.kicad.kicad", "--window", "4294967296", "--since", "990", "wait", "--ms", "1"],
            ["act", "--bundle", "org.kicad.kicad", "--window", "7", "--since", "990", "wait", "--ms"],
            ["--act"],
            ["capture", "--bundle", "org.kicad.kicad", "--window", "7", "--max-edge", "255"],
            ["capture", "--bundle", "org.kicad.kicad", "--window", "7", "--max-edge", "2049"],
            ["capture", "--bundle", "org.kicad.kicad", "--window", "7", "--max-edge", "big"],
            ["identify", "--x", "1"],
        ] {
            XCTAssertEqual(code(invoke(port, argv)), "usage", argv.joined(separator: " "))
        }
        XCTAssertEqual(port.posted, [])
    }

    func testAnAppOffTheListIsRefusedEvenWhenItIsFrontmost() {
        let port = FakePort()
        port.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "Terminal"),
                                   window: FakePort.kicadWindow)
        XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "40"], bundle: "com.apple.Terminal")),
                       "app_not_allowed")
        XCTAssertEqual(port.posted, [])
    }

    func testOurOwnPreviousActionIsNotMistakenForTheUser() {
        let port = FakePort()
        port.idle = 10.2 // last HID event ~ when our previous action finished (since = clock − 10)
        let r = act(port, ["click", "--x", "1", "--y", "40"], since: "990")
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["finishedAt"] as? Double, 1_000, "the next --since comes from this clock")
    }

    func testIdentifyReportsTheHelperClockForTheFirstSince() {
        XCTAssertEqual(invoke(FakePort(), ["identify"])["now"] as? Double, 1_000)
    }

    func testMalformedInvocationsAreUsageErrors() {
        let port = FakePort()
        XCTAssertEqual(code(invoke(port, ["launch"])), "usage")
        XCTAssertEqual(code(invoke(port, ["act", "--bundle", "org.kicad.kicad", "--window", "7", "click",
                                       "--x", "1", "--y", "1"])), "usage") // no --since
        XCTAssertEqual(code(act(port, ["click", "--x", "1.5", "--y", "1"])), "usage")
        XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "1", "--button", "middle"])), "usage")
        XCTAssertEqual(port.posted, [])
    }
}

final class ActEventTests: XCTestCase {
    func testClickPostsInGlobalCoordinatesFromTheLiveWindowBounds() {
        let port = FakePort()
        let r = act(port, ["click", "--x", "10", "--y", "40"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        let p = Point(x: 110, y: 90)
        XCTAssertEqual(port.posted, [.mouseMove(p), .mouseDown(.left, p, clicks: 1), .mouseUp(.left, p, clicks: 1)])
        XCTAssertEqual(port.postedPids, [nil, nil, nil], "pointer events are hit-tested, then posted globally")
    }

    func testDoubleClickAndASingleRightClick() {
        let port = FakePort()
        _ = act(port, ["click", "--x", "0", "--y", "30", "--count", "2"])
        let p = Point(x: 100, y: 80)
        XCTAssertEqual(port.posted, [
            .mouseMove(p),
            .mouseDown(.left, p, clicks: 1), .mouseUp(.left, p, clicks: 1),
            .mouseDown(.left, p, clicks: 2), .mouseUp(.left, p, clicks: 2),
        ])
        let right = FakePort()
        _ = act(right, ["click", "--x", "0", "--y", "30", "--button", "right"])
        XCTAssertEqual(right.posted, [.mouseMove(p), .mouseDown(.right, p, clicks: 1), .mouseUp(.right, p, clicks: 1)])
    }

    func testDragMovesThroughToTheEnd() {
        let port = FakePort()
        _ = act(port, ["drag", "--x", "0", "--y", "30", "--to-x", "100", "--to-y", "30"])
        XCTAssertEqual(port.posted.first, .mouseMove(Point(x: 100, y: 80)))
        XCTAssertEqual(port.posted.last, .mouseUp(.left, Point(x: 200, y: 80), clicks: 1))
        XCTAssertTrue(port.posted.contains(.mouseDrag(Point(x: 200, y: 80))))
        XCTAssertTrue(port.posted.contains(.mouseDrag(Point(x: 110, y: 80))), "10 even steps")
    }

    func testScrollAtAPoint() {
        let port = FakePort()
        _ = act(port, ["scroll", "--x", "5", "--y", "35", "--dy", "-3"])
        let at = Point(x: 105, y: 85)
        XCTAssertEqual(port.posted, [.mouseMove(at), .scroll(at, dx: 0, dy: -3)])
        XCTAssertEqual(port.postedPids, [nil, nil], "scroll is a pointer event: hit-tested, posted globally")
    }

    func testAllowedChordPostsKeyDownAndUpWithItsModifiers() {
        let port = FakePort()
        XCTAssertEqual(act(port, ["key", "--chord", "Shift+Cmd+Z"])["ok"] as? Bool, true)
        let z = KeyMap.code(for: "z")!
        XCTAssertEqual(port.posted, [.keyDown(z, [.command, .shift]), .keyUp(z, [.command, .shift])])
        XCTAssertEqual(port.postedPids, [42, 42], "keys go to the bound app's process only")
    }

    func testTypePostsTheTextAsIs() {
        let port = FakePort()
        _ = act(port, ["type", "--text", "10k Ω"])
        XCTAssertEqual(port.posted, [.text("10k Ω")])
        XCTAssertEqual(port.postedPids, [42])
    }

    func testWaitPostsNothingButSleeps() {
        let port = FakePort()
        XCTAssertEqual(act(port, ["wait", "--ms", "200"])["ok"] as? Bool, true)
        XCTAssertEqual(port.posted, [.sleep(milliseconds: 200)])
        XCTAssertEqual(port.postedPids, [nil])
    }
}

// ADR-041 amendment (M2): the bound process must be working inside the linked
// workspace, checked on every command; no path ever appears in the output.
final class WorkspaceBindingTests: XCTestCase {
    func testEveryCommandNeedsAnAbsoluteWorkspaceThatIsNotTheRoot() {
        for argv in [["identify"], ["capture", "--bundle", "org.kicad.kicad", "--window", "7"],
                     ["act", "--bundle", "org.kicad.kicad", "--window", "7", "--since", "990", "wait", "--ms", "1"]] {
            XCTAssertEqual(code(invoke(FakePort(), argv, within: nil)), "usage", "\(argv[0]) without --within")
            XCTAssertEqual(code(invoke(FakePort(), argv, within: "work")), "usage", "relative")
            XCTAssertEqual(code(invoke(FakePort(), argv, within: "/")), "usage", "the whole disk")
            let port = FakePort()
            port.resolve = { _ in nil }
            XCTAssertEqual(code(invoke(port, argv)), "usage", "a workspace that does not resolve")
        }
    }

    func testIdentifyHidesAKiCadWorkingOnAnotherProject() {
        let port = FakePort()
        port.cwd[42] = "/other-team/board"
        let r = invoke(port, ["identify"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["allowed"] as? Bool, false)
        XCTAssertEqual(r["outsideWorkspace"] as? Bool, true)
        XCTAssertTrue(r["app"] is NSNull && r["window"] is NSNull, "another project's title never leaves")
        XCTAssertNotNil(r["now"])
    }

    func testIdentifyAllowsTheWorkspaceItselfAndAnythingBelowIt() {
        for dir in ["/work", "/work/board", "/work/a/b"] {
            let port = FakePort()
            port.cwd[42] = dir
            let r = invoke(port, ["identify"])
            XCTAssertEqual(r["allowed"] as? Bool, true, dir)
            XCTAssertEqual(r["outsideWorkspace"] as? Bool, false, dir)
        }
    }

    func testAPrefixSiblingIsNotInside() {
        let port = FakePort()
        port.cwd[42] = "/work-other/board"
        XCTAssertEqual(invoke(port, ["identify"])["allowed"] as? Bool, false)
    }

    func testTheWorkspaceIsComparedResolved() {
        let port = FakePort()
        port.resolve = { $0 == "/link" ? "/work" : $0 }
        XCTAssertEqual(invoke(port, ["identify"], within: "/link")["allowed"] as? Bool, true)
    }

    func testAnUnreadableWorkingDirectoryFailsClosed() {
        let port = FakePort()
        port.cwd = [:]
        XCTAssertEqual(invoke(port, ["identify"])["allowed"] as? Bool, false)
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "7"])),
                       "outside_workspace")
        XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "40"])), "outside_workspace")
        XCTAssertTrue(port.posted.isEmpty)
    }

    func testCaptureAndActRefuseAnotherProjectAndPostNothing() {
        let port = FakePort()
        port.cwd[42] = "/other-team/board"
        let capture = invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "7"])
        XCTAssertEqual(code(capture), "outside_workspace")
        XCTAssertNil(capture["png"])
        let acted = act(port, ["type", "--text", "R1"])
        XCTAssertEqual(code(acted), "outside_workspace")
        XCTAssertFalse("\(acted)".contains("/other-team"), "no path in the refusal")
        XCTAssertTrue(port.posted.isEmpty)
    }

    func testCaptureChecksTheProcessThatOwnsTheWindow() {
        let port = FakePort()
        port.cwd[43] = "/other-team/board"
        port.windows[7] = WindowInfo(id: 7, title: "x", bounds: FakePort.kicadWindow.bounds,
                                     ownerBundleId: "org.kicad.kicad", ownerPid: 43, onScreen: true)
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "7"])),
                       "outside_workspace")
    }

    func testAProjectSwitchMidVerbStopsBeforeTheNextEvent() {
        let port = FakePort()
        port.afterPost = { $0.cwd[42] = "/other-team/board" }
        let r = act(port, ["click", "--x", "10", "--y", "40"])
        XCTAssertEqual(code(r), "outside_workspace")
        XCTAssertEqual(r["postedEvents"] as? Int, 1)
        XCTAssertEqual(port.posted.count, 1)
    }

    func testPathsCompareByteForByte() {
        let port = FakePort()
        port.cwd[42] = "/work/Re\u{0301}sistance"  // NFD
        XCTAssertEqual(invoke(port, ["identify"], within: "/work/R\u{00E9}sistance")["allowed"] as? Bool, false)
        XCTAssertEqual(invoke(port, ["identify"], within: "/work/Re\u{0301}sistance")["allowed"] as? Bool, true)
    }
}
