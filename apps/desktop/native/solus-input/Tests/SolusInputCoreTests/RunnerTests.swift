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
    var secure = false
    var idle: Double = 100
    var clock: Double = 1_000
    var posted: [SyntheticEvent] = []
    var image = CapturedImage(png: Data([0x89, 0x50]), imageWidth: 1568, imageHeight: 1176)

    static let kicadWindow = WindowInfo(
        id: 7, title: "board — Schematic Editor",
        bounds: Rect(x: 100, y: 50, width: 800, height: 600),
        ownerBundleId: "org.kicad.kicad", onScreen: true)

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
    func focusedElementIsSecure() -> Bool { secure }
    func secondsSinceLastPhysicalInput() -> Double { idle }
    func now() -> Double { clock }
    func capture(window: WindowInfo, maxEdge: Int) throws -> CapturedImage { image }
    func post(_ event: SyntheticEvent) { posted.append(event) }
}

private func invoke(_ port: FakePort, _ argv: [String]) -> [String: Any] {
    let line = Runner(port: port).run(argv)
    XCTAssertFalse(line.contains("\n"), "exactly one JSON line")
    let object = try? JSONSerialization.jsonObject(with: Data(line.utf8))
    return object as? [String: Any] ?? [:]
}

private func act(_ port: FakePort, _ verb: [String], bundle: String = "org.kicad.kicad",
                 window: String = "7", since: String = "990") -> [String: Any] {
    invoke(port, ["act", "--bundle", bundle, "--window", window, "--since", since] + verb)
}

private func code(_ result: [String: Any]) -> String? { result["code"] as? String }

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
        let r = invoke(port, ["identify"])
        XCTAssertEqual(r["allowed"] as? Bool, false)
        XCTAssertTrue(r["window"] is NSNull)
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
                                     ownerBundleId: "org.kicad.eeschema", onScreen: true)
        XCTAssertEqual(code(invoke(port, ["capture", "--bundle", "org.kicad.kicad", "--window", "8"])),
                       "window_mismatch")
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
            ("untrusted", { $0.trusted = false }, ["click", "--x", "1", "--y", "1"], "not_trusted"),
            ("other app in front", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "T"),
                                         window: nil)
            }, ["click", "--x", "1", "--y", "1"], "not_frontmost"),
            ("other window in front", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: "org.kicad.kicad", pid: 42, name: "KiCad"),
                                         window: WindowInfo(id: 9, title: "x",
                                                            bounds: Rect(x: 0, y: 0, width: 50, height: 50),
                                                            ownerBundleId: "org.kicad.kicad", onScreen: true))
            }, ["click", "--x", "1", "--y", "1"], "window_mismatch"),
            ("x past the edge", { _ in }, ["click", "--x", "800", "--y", "1"], "out_of_bounds"),
            ("negative y", { _ in }, ["move", "--x", "1", "--y", "-1"], "out_of_bounds"),
            ("drag end outside", { _ in },
             ["drag", "--x", "1", "--y", "1", "--to-x", "1", "--to-y", "600"], "out_of_bounds"),
            ("user moved", { $0.idle = 0.3 }, ["click", "--x", "1", "--y", "1"], "user_active"),
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

    func testAnAppOffTheListIsRefusedEvenWhenItIsFrontmost() {
        let port = FakePort()
        port.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "Terminal"),
                                   window: FakePort.kicadWindow)
        XCTAssertEqual(code(act(port, ["click", "--x", "1", "--y", "1"], bundle: "com.apple.Terminal")),
                       "app_not_allowed")
        XCTAssertEqual(port.posted, [])
    }

    func testOurOwnPreviousActionIsNotMistakenForTheUser() {
        let port = FakePort()
        port.idle = 10.2 // last HID event ~ when our previous action finished (since = clock − 10)
        XCTAssertEqual(act(port, ["click", "--x", "1", "--y", "1"], since: "990")["ok"] as? Bool, true)
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
        let r = act(port, ["click", "--x", "10", "--y", "20"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        let p = Point(x: 110, y: 70)
        XCTAssertEqual(port.posted, [.mouseMove(p), .mouseDown(.left, p, clicks: 1), .mouseUp(.left, p, clicks: 1)])
    }

    func testDoubleRightClick() {
        let port = FakePort()
        _ = act(port, ["click", "--x", "0", "--y", "0", "--button", "right", "--count", "2"])
        let p = Point(x: 100, y: 50)
        XCTAssertEqual(port.posted, [
            .mouseMove(p),
            .mouseDown(.right, p, clicks: 1), .mouseUp(.right, p, clicks: 1),
            .mouseDown(.right, p, clicks: 2), .mouseUp(.right, p, clicks: 2),
        ])
    }

    func testDragMovesThroughToTheEnd() {
        let port = FakePort()
        _ = act(port, ["drag", "--x", "0", "--y", "0", "--to-x", "100", "--to-y", "0"])
        XCTAssertEqual(port.posted.first, .mouseMove(Point(x: 100, y: 50)))
        XCTAssertEqual(port.posted.last, .mouseUp(.left, Point(x: 200, y: 50), clicks: 1))
        XCTAssertTrue(port.posted.contains(.mouseDrag(Point(x: 200, y: 50))))
    }

    func testScrollAtAPoint() {
        let port = FakePort()
        _ = act(port, ["scroll", "--x", "5", "--y", "5", "--dy", "-3"])
        XCTAssertEqual(port.posted, [.mouseMove(Point(x: 105, y: 55)), .scroll(dx: 0, dy: -3)])
    }

    func testAllowedChordPostsKeyDownAndUpWithItsModifiers() {
        let port = FakePort()
        XCTAssertEqual(act(port, ["key", "--chord", "Shift+Cmd+Z"])["ok"] as? Bool, true)
        let z = KeyMap.code(for: "z")!
        XCTAssertEqual(port.posted, [.keyDown(z, [.command, .shift]), .keyUp(z, [.command, .shift])])
    }

    func testTypePostsTheTextAsIs() {
        let port = FakePort()
        _ = act(port, ["type", "--text", "10k Ω"])
        XCTAssertEqual(port.posted, [.text("10k Ω")])
    }

    func testWaitPostsNothingButSleeps() {
        let port = FakePort()
        XCTAssertEqual(act(port, ["wait", "--ms", "200"])["ok"] as? Bool, true)
        XCTAssertEqual(port.posted, [.sleep(milliseconds: 200)])
    }
}
