// SOLUSDEV-319 slice 4 — frontmost-app driving (sol-drive.md §2.2, ADR-041
// 2026-10-31): the denylist, project- vs window-bound apps, the `front` shape of
// `identify`, `--pid` on capture/act and the denied chords.
import Foundation
import XCTest
@testable import SolusInputCore

/// A window-bound app (not denied, not KiCad) in front: Blender, pid 77, window 11.
private let blender = "org.blenderfoundation.blender"
private let blenderWindow = WindowInfo(
    id: 11, title: "bracket.blend — Blender", bounds: Rect(x: 200, y: 100, width: 1000, height: 750),
    ownerBundleId: blender, ownerPid: 77, onScreen: true)

private func blenderPort() -> FakePort {
    let port = FakePort()
    port.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 77, name: "Blender"), window: blenderWindow)
    port.windows[11] = blenderWindow
    return port
}

private func front(_ result: [String: Any]) -> [String: Any]? { result["front"] as? [String: Any] }

private func capture(_ port: FakePort, bundle: String = blender, window: String = "11", pid: String? = "77",
                     within: String? = nil) -> [String: Any] {
    invoke(port, ["capture", "--bundle", bundle, "--window", window] + (pid.map { ["--pid", $0] } ?? []),
           within: within)
}

private func drive(_ port: FakePort, _ verb: [String], bundle: String = blender, window: String = "11",
                   pid: String? = "77", within: String? = nil) -> [String: Any] {
    invoke(port, ["act", "--bundle", bundle, "--window", window, "--since", "990"]
        + (pid.map { ["--pid", $0] } ?? []) + verb, within: within)
}

final class AppPolicyTests: XCTestCase {
    func testEveryListedAppIsDenied() {
        for id in ["com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable", "dev.warp.Warp-Preview",
                   "com.mitchellh.ghostty", "net.kovidgoyal.kitty", "org.alacritty", "com.github.wez.wezterm",
                   "co.zeit.hyper", "com.apple.ScriptEditor2", "com.apple.Automator", "com.apple.shortcuts",
                   "com.latenightsw.ScriptDebugger8", "com.apple.finder",
                   "com.1password.1password", "com.agilebits.onepassword7", "com.bitwarden.desktop",
                   "com.dashlane.dashlanephonefinal", "com.lastpass.LastPass", "org.keepassxc.keepassxc",
                   "com.apple.keychainaccess", "com.apple.Passwords", "com.apple.SecurityAgent",
                   "com.apple.loginwindow", "com.apple.coreservices.uiagent", "com.apple.UserNotificationCenter",
                   "com.apple.systempreferences", "com.apple.settings", "com.apple.SystemSettings",
                   "com.apple.ActivityMonitor", "com.apple.DiskUtility", "com.apple.installer",
                   "com.apple.mail", "com.microsoft.Outlook", "com.readdle.smartemail-Mac", "com.readdle.SparkDesktop",
                   "org.mozilla.thunderbird", "com.mimestream.Mimestream", "com.apple.MobileSMS", "com.apple.FaceTime",
                   "com.tinyspeck.slackmacgap", "com.hnc.Discord", "com.microsoft.teams2", "com.microsoft.teams",
                   "net.whatsapp.WhatsApp", "ru.keepcoder.Telegram", "org.telegram.desktop",
                   "org.whispersystems.signal-desktop", "us.zoom.xos", "com.apple.Safari",
                   "com.apple.SafariTechnologyPreview", "com.google.Chrome", "org.chromium.Chromium",
                   "org.mozilla.firefox", "org.mozilla.firefoxdeveloperedition", "org.mozilla.nightly",
                   "company.thebrowser.Browser", "company.thebrowser.dia", "com.microsoft.edgemac",
                   "com.brave.Browser", "com.operasoftware.Opera", "com.operasoftware.OperaGX",
                   "com.vivaldi.Vivaldi", "com.kagi.kagimacOS", "app.zen-browser.zen",
                   "com.solusforge.solus", "com.github.Electron"] {
            XCTAssertTrue(DeniedApps.denies(id), id)
            XCTAssertEqual(AppPolicy.classify(id), .denied, id)
        }
    }

    func testFamilyEntriesCoverTheirDottedChildrenOnly() {
        for id in ["com.google.Chrome.canary", "com.google.Chrome.beta", "com.google.Chrome.app.abcdef",
                   "com.microsoft.edgemac.Beta", "com.microsoft.edgemac.Dev", "com.microsoft.edgemac.Canary",
                   "com.brave.Browser.beta", "com.brave.Browser.nightly", "com.operasoftware.Opera.beta",
                   "com.vivaldi.Vivaldi.snapshot", "com.apple.Passwords.MenuBarExtra",
                   "com.apple.systempreferences.GeneralSettings", "com.apple.settings.PrivacySecurity.extension"] {
            XCTAssertTrue(DeniedApps.denies(id), id)
        }
        for id in ["com.google.Chromecast", "com.operasoftware.OperaNext", "com.apple.settingsX",
                   "com.brave.BrowserX"] {
            XCTAssertFalse(DeniedApps.denies(id), id)
        }
    }

    func testFinderIsDeniedAsAGeneralPurposeHost() {
        // Finder opens and runs anything (apps, scripts, installers): a code-execution host.
        XCTAssertTrue(DeniedApps.denies("com.apple.finder"))
        XCTAssertEqual(AppPolicy.classify("com.apple.finder"), .denied)
        XCTAssertEqual(AppPolicy.classify("com.apple.finder.Open-iCloudDrive"), .windowBound)
    }

    func testRemoteDesktopLauncherReplAndImagerClassesAreDenied() {
        // ADR-041 amendment 2026-11-01 (M-1): terminals by another name.
        for id in ["com.apple.ScreenSharing", "com.microsoft.rdc.macos", "com.utmapp.UTM", "com.vmware.fusion",
                   "com.teamviewer.TeamViewer", "com.philandro.anydesk", "com.realvnc.vncviewer", "tv.parsec.www",
                   "com.raycast.macos", "org.hammerspoon.Hammerspoon", "org.python.IDLE", "org.thonny.Thonny",
                   "io.balena.etcher", "org.raspberrypi.imagingutility",
                   "org.mujoco.mujoco", "org.python.python",
                   "com.parallels.desktop.console", "org.virtualbox.app.VirtualBox", "com.p5sys.jump.mac.viewer",
                   "com.runningwithcrayons.Alfred", "com.stairways.keyboardmaestro.editor"] {
            XCTAssertTrue(DeniedApps.denies(id), id)
            XCTAssertEqual(AppPolicy.classify(id), .denied, id)
        }
    }

    func testExactEntriesAreByteExactAndNotFamilies() {
        for id in ["com.apple.Terminal.helper", "com.apple.mail.extension", "com.apple.terminal", "COM.APPLE.MAIL",
                   "com.apple.Safari2"] {
            XCTAssertFalse(DeniedApps.denies(id), id)
            XCTAssertEqual(AppPolicy.classify(id), .windowBound, id)
        }
    }

    func testSolusAndUnpackagedElectronAreAlwaysDenied() {
        for id in ["com.solusforge.solus", "com.solusforge.solus.helper", "com.solusforge.solus.helper.Renderer",
                   "com.solusforge.solus.input", "com.solusforge.solus.companion", "com.github.Electron",
                   "com.github.Electron.helper"] {
            XCTAssertEqual(AppPolicy.classify(id), .denied, id)
        }
        XCTAssertEqual(AppPolicy.classify("com.solusforge.soluslike"), .windowBound)
    }

    func testUnusableBundleIdsAreDenied() {
        for id in ["", "-abc", ".abc", "com apple", "com/apple", "com.äpple", "com_apple",
                   String(repeating: "a", count: 129)] {
            XCTAssertFalse(DeniedApps.isUsable(id), id)
            XCTAssertEqual(AppPolicy.classify(id), .denied, id)
        }
        XCTAssertTrue(DeniedApps.isUsable(String(repeating: "a", count: 128)))
        XCTAssertTrue(DeniedApps.isUsable("9lives.app-x"))
    }

    func testKiCadIsTheOnlyProjectBoundApp() {
        XCTAssertEqual(ProjectBoundApps.bundleIds, ["org.kicad.kicad", "org.kicad.eeschema"])
        XCTAssertEqual(AppPolicy.classify("org.kicad.kicad"), .projectBound)
        XCTAssertEqual(AppPolicy.classify("org.kicad.eeschema"), .projectBound)
        XCTAssertEqual(AppPolicy.classify("org.kicad.pcbnew"), .windowBound)
        XCTAssertEqual(AppPolicy.classify(blender), .windowBound)
    }
}

final class FrontIdentifyTests: XCTestCase {
    func testAWindowBoundAppReportsItsFullBindingWithoutAWorkspace() throws {
        let r = invoke(blenderPort(), ["identify"], within: nil)
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["now"] as? Double, 1_000)
        XCTAssertEqual(r["unsignedDev"] as? Bool, false)
        XCTAssertNotNil(r["trust"])
        for removed in ["allowed", "app", "window", "outsideWorkspace"] { XCTAssertNil(r[removed], removed) }
        let f = try XCTUnwrap(front(r))
        XCTAssertEqual(Set(f.keys), ["drivable", "binding", "bundleId", "name", "pid", "windowId", "title",
                                     "bounds", "documentDir"])
        XCTAssertEqual(f["drivable"] as? Bool, true)
        XCTAssertEqual(f["binding"] as? String, "window")
        XCTAssertEqual(f["bundleId"] as? String, blender)
        XCTAssertEqual(f["name"] as? String, "Blender")
        XCTAssertEqual(f["pid"] as? Int, 77)
        XCTAssertEqual(f["windowId"] as? Int, 11)
        XCTAssertEqual(f["title"] as? String, "bracket.blend — Blender")
        XCTAssertEqual(f["bounds"] as? [String: Int], ["x": 200, "y": 100, "width": 1000, "height": 750])
        XCTAssertTrue(f["documentDir"] is NSNull, "no --within, no documentDir")
    }

    func testDocumentDirIsRelativeToTheWorkspaceAndNeverAbsolute() {
        let cases: [(String?, Any)] = [
            ("/work/parts/bracket.blend", "parts"), ("/work/bracket.blend", ""),
            ("/work/a/b/c.blend", "a/b"), ("/elsewhere/bracket.blend", NSNull()),
            ("/work-other/x.blend", NSNull()), (nil, NSNull()),
        ]
        for (document, expected) in cases {
            let port = blenderPort()
            if let document { port.documents[11] = document }
            let dir = front(invoke(port, ["identify"], within: "/work"))?["documentDir"]
            if let expected = expected as? String {
                XCTAssertEqual(dir as? String, expected, document ?? "none")
            } else {
                XCTAssertTrue(dir is NSNull, document ?? "none")
            }
        }
    }

    func testDocumentDirIsResolvedBeforeComparing() {
        let port = blenderPort()
        port.documents[11] = "/link/parts/bracket.blend"
        port.resolve = { $0.hasPrefix("/link/") ? "/work/" + $0.dropFirst("/link/".count) : $0 }
        XCTAssertEqual(front(invoke(port, ["identify"], within: "/work"))?["documentDir"] as? String, "parts")
        port.resolve = { $0.hasSuffix(".blend") ? nil : $0 } // the document does not resolve
        XCTAssertTrue(front(invoke(port, ["identify"], within: "/work"))?["documentDir"] is NSNull)
    }

    func testAWindowBoundAppWithNoOrdinaryWindowHasNothingToBind() throws {
        let port = blenderPort()
        port.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 77, name: "Blender"), window: nil)
        let f = try XCTUnwrap(front(invoke(port, ["identify"], within: nil)))
        XCTAssertEqual(f["drivable"] as? Bool, true)
        XCTAssertEqual(f["pid"] as? Int, 77)
        for key in ["windowId", "title", "bounds", "documentDir"] { XCTAssertTrue(f[key] is NSNull, key) }
    }

    func testTitleIsNullWithoutScreenRecordingOrWhenEmpty() {
        let port = blenderPort()
        port.screenRecording = false
        XCTAssertTrue(front(invoke(port, ["identify"], within: nil))?["title"] is NSNull)
        let untitled = blenderPort()
        let bare = WindowInfo(id: 11, title: "", bounds: blenderWindow.bounds, ownerBundleId: blender,
                              ownerPid: 77, onScreen: true)
        untitled.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 77, name: "Blender"), window: bare)
        XCTAssertTrue(front(invoke(untitled, ["identify"], within: nil))?["title"] is NSNull)
    }

    /// The API's visible-text rule is "no Cc/Cf/Co/Cn/Cs/Zl/Zp" (binding.py `_HIDDEN`):
    /// unassigned and supplementary private-use scalars are dropped here too.
    func testCleaningDropsUnassignedAndEveryPrivateUseScalar() {
        for value: UInt32 in [0x0378, 0x0E0080, 0xE000, 0xF0000, 0x10FFFD, 0x2028, 0x2029, 0x200B, 0x7] {
            let scalar = Unicode.Scalar(value)!
            XCTAssertFalse(Runner.isVisibleText(scalar), String(value, radix: 16))
        }
        XCTAssertEqual(Runner.cleaned("Cu\u{0378}ra\u{F0000} 5\u{E0080}", max: 64), "Cura 5")
        XCTAssertEqual(Runner.cleaned("R1 = 10k Ω, 5% é", max: 64), "R1 = 10k Ω, 5% é")
    }

    func testNameAndTitleAreCleanedAndTruncated() throws {
        let port = blenderPort()
        let title = "a\u{0}b\u{7}c\u{200B}\u{2028}" + String(repeating: "t", count: 300)
        let window = WindowInfo(id: 11, title: title, bounds: blenderWindow.bounds, ownerBundleId: blender,
                                ownerPid: 77, onScreen: true)
        port.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 77,
                                                name: "Ble\u{1B}nder\n" + String(repeating: "n", count: 100)),
                                   window: window)
        let f = try XCTUnwrap(front(invoke(port, ["identify"], within: nil)))
        let cleanedTitle = try XCTUnwrap(f["title"] as? String)
        XCTAssertTrue(cleanedTitle.hasPrefix("abct"))
        XCTAssertEqual(cleanedTitle.unicodeScalars.count, 256)
        let name = try XCTUnwrap(f["name"] as? String)
        XCTAssertTrue(name.hasPrefix("Blendern"))
        XCTAssertEqual(name.unicodeScalars.count, 64)
    }

    func testADeniedAppReportsOnlyItsIdentityAndReason() throws {
        let port = FakePort()
        let mail = WindowInfo(id: 3, title: "Re: salary review", bounds: Rect(x: 0, y: 0, width: 9, height: 9),
                              ownerBundleId: "com.apple.mail", ownerPid: 9, onScreen: true)
        port.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.mail", pid: 9, name: "Mail"), window: mail)
        port.documents[3] = "/work/secret.eml"
        let line = Runner(port: port, unsignedDev: false).run(["identify", "--within", "/work"])
        XCTAssertFalse(line.contains("salary"), "never a denied app's title")
        let f = try XCTUnwrap(front(invoke(port, ["identify"])))
        XCTAssertEqual(Set(f.keys), ["drivable", "bundleId", "name", "binding", "reason"])
        XCTAssertEqual(f["drivable"] as? Bool, false)
        XCTAssertEqual(f["bundleId"] as? String, "com.apple.mail")
        XCTAssertEqual(f["name"] as? String, "Mail")
        XCTAssertTrue(f["binding"] is NSNull)
        XCTAssertEqual(f["reason"] as? String, "denied")
    }

    func testSolusItselfInFrontIsDenied() {
        for id in ["com.solusforge.solus", "com.github.Electron"] {
            let port = FakePort()
            port.front = FrontmostInfo(app: AppInfo(bundleId: id, pid: 5, name: "Solus"), window: blenderWindow)
            let f = front(invoke(port, ["identify"], within: nil))
            XCTAssertEqual(f?["reason"] as? String, "denied", id)
            XCTAssertNil(f?["pid"], id)
        }
    }

    func testNothingInFrontOrAnUnusableBundleIdIsNull() {
        let port = FakePort()
        port.front = nil
        XCTAssertTrue(invoke(port, ["identify"], within: nil)["front"] is NSNull)
        port.front = FrontmostInfo(app: AppInfo(bundleId: "bad id", pid: 5, name: "X"), window: blenderWindow)
        let line = Runner(port: port, unsignedDev: false).run(["identify"])
        XCTAssertTrue(invoke(port, ["identify"], within: nil)["front"] is NSNull)
        XCTAssertFalse(line.contains("bad id"))
    }

    func testKiCadWithoutAWorkspaceIsNotDrivable() throws {
        let f = try XCTUnwrap(front(invoke(FakePort(), ["identify"], within: nil)))
        XCTAssertEqual(Set(f.keys), ["drivable", "bundleId", "name", "binding", "reason"])
        XCTAssertEqual(f["drivable"] as? Bool, false)
        XCTAssertEqual(f["binding"] as? String, "project")
        XCTAssertEqual(f["reason"] as? String, "no_workspace")
    }

    func testKiCadOutsideTheWorkspaceHidesItsWindow() throws {
        let port = FakePort()
        port.cwd[42] = "/other-team/board"
        let line = Runner(port: port, unsignedDev: false).run(["identify", "--within", "/work"])
        XCTAssertFalse(line.contains("Schematic"), "another project's title never leaves")
        let f = try XCTUnwrap(front(invoke(port, ["identify"])))
        XCTAssertEqual(Set(f.keys), ["drivable", "bundleId", "name", "binding", "reason"])
        XCTAssertEqual(f["reason"] as? String, "outside_workspace")
        XCTAssertEqual(f["binding"] as? String, "project")
    }

    func testKiCadInsideTheWorkspaceIsProjectBound() throws {
        let f = try XCTUnwrap(front(invoke(FakePort(), ["identify"])))
        XCTAssertEqual(f["drivable"] as? Bool, true)
        XCTAssertEqual(f["binding"] as? String, "project")
        XCTAssertEqual(f["pid"] as? Int, 42)
        XCTAssertEqual(f["windowId"] as? Int, 7)
        XCTAssertEqual(f["title"] as? String, "board — Schematic Editor")
        XCTAssertTrue(f["documentDir"] is NSNull, "KiCad exposes no AXDocument")
    }

    func testAPresentWorkspaceIsStillValidated() {
        for within in ["work", "/", "/Users/me", "/Users"] {
            XCTAssertEqual(code(invoke(blenderPort(), ["identify"], within: within)), "usage", within)
        }
    }
}

final class FrontCaptureTests: XCTestCase {
    func testAWindowBoundWindowIsCapturedWithItsPidAndNoWorkspace() {
        let r = capture(blenderPort())
        XCTAssertEqual(r["ok"] as? Bool, true)
        XCTAssertEqual(r["pointsWidth"] as? Int, 1000)
    }

    func testAWindowBoundBundleNeedsAPid() {
        XCTAssertEqual(code(capture(blenderPort(), pid: nil)), "usage")
    }

    func testMalformedPidsAreUsageErrors() {
        for pid in ["0", "-1", "2147483648", "abc", "+77", "77.0", "", " 77", "0077x"] {
            XCTAssertEqual(code(capture(blenderPort(), pid: pid)), "usage", pid)
        }
        XCTAssertEqual(capture(blenderPort(), pid: "77")["ok"] as? Bool, true)
    }

    func testDeniedBundlesAreRefusedFirst() {
        let port = blenderPort()
        for id in ["com.apple.Terminal", "com.google.Chrome.canary", "com.solusforge.solus", "", "bad id"] {
            XCTAssertEqual(code(capture(port, bundle: id, window: "999")), "app_denied", id)
            XCTAssertEqual(code(capture(port, bundle: id, window: "999", pid: nil)), "app_denied", id)
        }
    }

    func testChecksRunInOrderWindowThenOwnerThenPid() {
        let port = blenderPort()
        XCTAssertEqual(code(capture(port, window: "12", pid: "1")), "window_not_found")
        port.windows[12] = WindowInfo(id: 12, title: "", bounds: blenderWindow.bounds, ownerBundleId: blender,
                                      ownerPid: 77, onScreen: false)
        XCTAssertEqual(code(capture(port, window: "12")), "window_not_found", "off screen")
        XCTAssertEqual(code(capture(port, window: "7", pid: "1")), "window_mismatch", "KiCad's window")
        XCTAssertEqual(code(capture(port, pid: "78")), "pid_mismatch")
    }

    func testTheWorkingDirectoryIsNotCheckedForAWindowBoundApp() {
        let port = blenderPort()
        port.cwd = [77: "/somewhere/else"]
        XCTAssertEqual(capture(port, within: "/work")["ok"] as? Bool, true)
    }

    func testKiCadStillNeedsItsWorkspaceAndChecksAGivenPid() {
        let port = FakePort()
        XCTAssertEqual(code(capture(port, bundle: "org.kicad.kicad", window: "7", pid: nil)), "usage")
        XCTAssertEqual(capture(port, bundle: "org.kicad.kicad", window: "7", pid: nil, within: "/work")["ok"] as? Bool,
                       true)
        XCTAssertEqual(code(capture(port, bundle: "org.kicad.kicad", window: "7", pid: "41", within: "/work")),
                       "pid_mismatch")
        port.cwd[42] = "/other-team/board"
        XCTAssertEqual(code(capture(port, bundle: "org.kicad.kicad", window: "7", pid: "42", within: "/work")),
                       "outside_workspace")
    }
}

final class FrontActTests: XCTestCase {
    func testAWindowBoundClickPostsAndKeysGoToThatPid() {
        let port = blenderPort()
        let r = drive(port, ["click", "--x", "10", "--y", "40"])
        XCTAssertEqual(r["ok"] as? Bool, true)
        let p = Point(x: 210, y: 140)
        XCTAssertEqual(port.posted, [.mouseMove(p), .mouseDown(.left, p, clicks: 1), .mouseUp(.left, p, clicks: 1)])
        XCTAssertEqual(drive(port, ["type", "--text", "M3"])["ok"] as? Bool, true)
        XCTAssertEqual(port.postedPids.last, 77)
    }

    func testBindingRefusalsPostNothing() {
        let cases: [(String, (FakePort) -> Void, String?, String)] = [
            ("no pid", { _ in }, nil, "usage"),
            ("bad pid", { _ in }, "0", "usage"),
            ("wrong pid", { _ in }, "78", "pid_mismatch"),
            ("relaunched: same bundle in front, new pid", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 99, name: "Blender"),
                                         window: WindowInfo(id: 15, title: "", bounds: blenderWindow.bounds,
                                                            ownerBundleId: blender, ownerPid: 99, onScreen: true))
            }, "77", "pid_mismatch"),
            ("another window of the app in front", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 77, name: "Blender"),
                                         window: WindowInfo(id: 12, title: "", bounds: blenderWindow.bounds,
                                                            ownerBundleId: blender, ownerPid: 77, onScreen: true))
            }, "77", "window_mismatch"),
            ("another app in front", {
                $0.front = FrontmostInfo(app: AppInfo(bundleId: "org.kicad.kicad", pid: 42, name: "KiCad"),
                                         window: FakePort.kicadWindow)
            }, "77", "not_frontmost"),
            ("window gone", { $0.windows[11] = nil }, "77", "window_not_found"),
        ]
        for (name, setup, pid, expected) in cases {
            let port = blenderPort()
            setup(port)
            XCTAssertEqual(code(drive(port, ["click", "--x", "10", "--y", "40"], pid: pid)), expected, name)
            XCTAssertEqual(port.posted, [], "\(name) must post nothing")
        }
    }

    func testDeniedBundlesAreRefusedEvenWhenInFront() {
        let port = FakePort()
        port.front = FrontmostInfo(app: AppInfo(bundleId: "com.apple.Terminal", pid: 9, name: "Terminal"),
                                   window: WindowInfo(id: 3, title: "zsh", bounds: blenderWindow.bounds,
                                                      ownerBundleId: "com.apple.Terminal", ownerPid: 9, onScreen: true))
        port.windows[3] = port.front?.window
        XCTAssertEqual(code(drive(port, ["type", "--text", "ls"], bundle: "com.apple.Terminal", window: "3", pid: "9")),
                       "app_denied")
        XCTAssertEqual(code(drive(port, ["type", "--text", "ls"], bundle: "com.solusforge.solus", window: "3", pid: "9")),
                       "app_denied")
        XCTAssertEqual(port.posted, [])
    }

    func testEveryExistingGuardStillAppliesToAWindowBoundApp() {
        let cases: [(String, (FakePort) -> Void, [String], String)] = [
            ("untrusted", { $0.trusted = false }, ["click", "--x", "10", "--y", "40"], "not_trusted"),
            ("password field", { $0.secure = true }, ["type", "--text", "x"], "secure_field"),
            ("unreadable focus", { $0.secure = nil }, ["key", "--chord", "return"], "secure_field"),
            ("covered", { p in p.windowAt = { _ in 99 } }, ["click", "--x", "10", "--y", "40"], "occluded"),
            ("kill switch", { $0.idle = 0.3 }, ["click", "--x", "10", "--y", "40"], "user_active"),
            ("off the window", { _ in }, ["click", "--x", "1000", "--y", "40"], "out_of_bounds"),
            ("title bar", { _ in }, ["click", "--x", "10", "--y", "5"], "window_chrome"),
            ("clipboard", { _ in }, ["key", "--chord", "cmd+v"], "chord_denied"),
        ]
        for (name, setup, verb, expected) in cases {
            let port = blenderPort()
            setup(port)
            XCTAssertEqual(code(drive(port, verb)), expected, name)
            XCTAssertEqual(port.posted, [], "\(name) must post nothing")
        }
    }

    func testARelaunchMidVerbStopsBeforeTheNextEvent() {
        let port = blenderPort()
        port.afterPost = { p in
            p.front = FrontmostInfo(app: AppInfo(bundleId: blender, pid: 99, name: "Blender"), window: blenderWindow)
        }
        let r = drive(port, ["click", "--x", "10", "--y", "40"])
        XCTAssertEqual(code(r), "focus_lost")
        XCTAssertEqual(r["postedEvents"] as? Int, 1)
    }

    func testTheWorkingDirectoryIsNotCheckedForAWindowBoundAppEvenWithAWorkspace() {
        let port = blenderPort()
        port.cwd = [:] // unreadable would fail a project-bound app closed
        XCTAssertEqual(drive(port, ["click", "--x", "10", "--y", "40"], within: "/work")["ok"] as? Bool, true)
        XCTAssertEqual(port.posted.count, 3)
    }

    func testKiCadIsUnchanged() {
        let port = FakePort()
        XCTAssertEqual(code(drive(port, ["wait", "--ms", "1"], bundle: "org.kicad.kicad", window: "7", pid: nil)),
                       "usage", "no workspace")
        XCTAssertEqual(drive(port, ["click", "--x", "1", "--y", "40"], bundle: "org.kicad.kicad", window: "7",
                             pid: nil, within: "/work")["ok"] as? Bool, true)
        XCTAssertEqual(code(drive(port, ["wait", "--ms", "1"], bundle: "org.kicad.kicad", window: "7", pid: "41",
                                  within: "/work")), "pid_mismatch")
        let other = FakePort()
        other.cwd[42] = "/other-team/board"
        XCTAssertEqual(code(drive(other, ["click", "--x", "1", "--y", "40"], bundle: "org.kicad.kicad", window: "7",
                                  pid: "42", within: "/work")), "outside_workspace")
        XCTAssertEqual(other.posted, [])
    }
}

final class DeniedChordTests: XCTestCase {
    static let denied = ["cmd+s", "cmd+shift+s", "cmd+option+s", "cmd+option+shift+s", "cmd+w", "cmd+shift+w",
                         "cmd+option+w", "cmd+q", "cmd+shift+q", "cmd+option+q", "cmd+option+shift+q", "cmd+p",
                         "cmd+shift+p", "cmd+option+p"]

    func testTheDeniedChordsAreExactlyTheSpecsInAnyOrderAndSpelling() {
        XCTAssertEqual(DeniedChords.chords.count, Self.denied.count)
        for text in Self.denied + ["shift+cmd+s", "alt+cmd+w", "Option+Shift+Command+Q", "opt+cmd+p"] {
            XCTAssertTrue(DeniedChords.denies(Chord.parse(text)!), text)
        }
        for text in ["cmd+z", "s", "shift+s", "cmd+shift+z", "ctrl+cmd+s"] {
            XCTAssertFalse(DeniedChords.denies(Chord.parse(text)!), text)
        }
    }

    func testEachDeniedChordIsRefusedForBothBindingsAndPostsNothing() {
        for text in Self.denied {
            let window = blenderPort()
            XCTAssertEqual(code(drive(window, ["key", "--chord", text])), "chord_denied", "window-bound \(text)")
            XCTAssertEqual(window.posted, [])
            let project = FakePort()
            XCTAssertEqual(code(drive(project, ["key", "--chord", text], bundle: "org.kicad.kicad", window: "7",
                                      pid: "42", within: "/work")), "chord_denied", "project-bound \(text)")
            XCTAssertEqual(project.posted, [])
        }
    }
}
