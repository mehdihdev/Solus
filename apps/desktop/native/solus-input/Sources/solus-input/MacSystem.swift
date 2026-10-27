// The real `SystemPort`: Accessibility, CoreGraphics event posting and window
// lists, ScreenCaptureKit capture. Kept thin — every decision is in
// SolusInputCore.Runner, which is unit-tested against a fake of this.
import AppKit
import ApplicationServices
import CoreGraphics
import ImageIO
import ScreenCaptureKit
import Security
import SolusInputCore
import UniformTypeIdentifiers

/// Stamped into `eventSourceUserData` on every event we post ("SOLUS").
let solusEventMarker: Int64 = 0x534F_4C55_53
/// A short gap between posted events so the target app sees each one.
let interEventMicros: useconds_t = 8_000
let captureTimeout: DispatchTimeInterval = .seconds(10)
/// HID event types that count as the user touching the machine.
let physicalInputTypes: [CGEventType] = [
    .mouseMoved, .leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp, .otherMouseDown,
    .otherMouseUp, .leftMouseDragged, .rightMouseDragged, .otherMouseDragged, .scrollWheel,
    .keyDown, .keyUp, .flagsChanged, .tabletPointer, .tabletProximity,
]
/// Fallback when a window's close button cannot be read.
let defaultTitleBarHeight = 28.0
/// Room below the traffic-light buttons that still belongs to the title bar.
let titleBarMargin = 4.0

/// Set by the SIGTERM handler (main.swift); read between posted events.
final class StopFlag: @unchecked Sendable {
    static let shared = StopFlag()
    private let lock = NSLock()
    private var raised = false
    func raise() { lock.lock(); raised = true; lock.unlock() }
    var isRaised: Bool { lock.lock(); defer { lock.unlock() }; return raised }
}

struct MacSystem: SystemPort {
    private let source = CGEventSource(stateID: .privateState)

    func accessibilityTrusted() -> Bool { AXIsProcessTrusted() }
    func screenRecordingAllowed() -> Bool { CGPreflightScreenCaptureAccess() }
    /// Monotonic (system uptime), like the HID idle counter it is compared with.
    func now() -> Double { ProcessInfo.processInfo.systemUptime }
    func stopRequested() -> Bool { StopFlag.shared.isRaised }

    func secondsSinceLastPhysicalInput() -> Double {
        physicalInputTypes
            .map { CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: $0) }
            .min() ?? .greatestFiniteMagnitude
    }

    /// The owner of the front-most ordinary (layer 0) window, read live from the
    /// window server — NSWorkspace.frontmostApplication is notification-backed
    /// and goes stale in a process with no run loop.
    func frontmost() -> FrontmostInfo? {
        guard let front = windowList([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            .first(where: { ($0[kCGWindowLayer as String] as? Int) == 0 }),
            let pid = front[kCGWindowOwnerPID as String] as? pid_t,
            let app = NSRunningApplication(processIdentifier: pid), let bundle = app.bundleIdentifier
        else { return nil }
        return FrontmostInfo(
            app: AppInfo(bundleId: bundle, pid: Int(pid), name: app.localizedName ?? bundle),
            window: windowInfo(front))
    }

    /// The kernel's record of the process's cwd (PROC_PIDVNODEPATHINFO) — the
    /// same answer `lsof` gives, without running it. Same-user processes only.
    func workingDirectory(pid: Int) -> String? {
        var info = proc_vnodepathinfo()
        let size = Int32(MemoryLayout<proc_vnodepathinfo>.size)
        guard proc_pidinfo(pid_t(pid), PROC_PIDVNODEPATHINFO, 0, &info, size) == size else { return nil }
        let path = withUnsafeBytes(of: info.pvi_cdir.vip_path) { raw in
            String(decoding: raw.prefix { $0 != 0 }, as: UTF8.self)
        }
        return path.hasPrefix("/") ? resolvedPath(path) : nil
    }

    // MARK: caller check (ADR-041 amendment 2026-10-27)

    func ownParentPid() -> Int { Int(getppid()) }

    func parentPid(of pid: Int) -> Int? {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        guard proc_pidinfo(pid_t(pid), PROC_PIDTBSDINFO, 0, &info, size) == size else { return nil }
        return Int(info.pbi_ppid)
    }

    /// `KERN_PROCARGS2` starts with the process's argc (an Int32).
    func argumentCount(pid: Int) -> Int? {
        var argmaxMib: [Int32] = [CTL_KERN, KERN_ARGMAX]
        var argmax: Int32 = 0
        var argmaxSize = MemoryLayout<Int32>.size
        guard sysctl(&argmaxMib, 2, &argmax, &argmaxSize, nil, 0) == 0, argmax > 0 else { return nil }
        var mib: [Int32] = [CTL_KERN, KERN_PROCARGS2, Int32(pid)]
        var buffer = [UInt8](repeating: 0, count: Int(argmax))
        var size = buffer.count
        guard sysctl(&mib, 3, &buffer, &size, nil, 0) == 0, size >= MemoryLayout<Int32>.size else { return nil }
        return Int(buffer.withUnsafeBytes { $0.loadUnaligned(as: Int32.self) })
    }

    func satisfies(pid: Int, requirement: String) -> Bool {
        var parsed: SecRequirement?
        guard SecRequirementCreateWithString(requirement as CFString, [], &parsed) == errSecSuccess,
              let parsed else { return false }
        var code: SecCode?
        let attributes = [kSecGuestAttributePid: NSNumber(value: pid)] as CFDictionary
        guard SecCodeCopyGuestWithAttributes(nil, attributes, [], &code) == errSecSuccess, let code else { return false }
        return SecCodeCheckValidity(code, [], parsed) == errSecSuccess
    }

    func ownCodeSatisfies(requirement: String) -> Bool {
        var parsed: SecRequirement?
        var code: SecCode?
        guard SecRequirementCreateWithString(requirement as CFString, [], &parsed) == errSecSuccess, let parsed,
              SecCodeCopySelf([], &code) == errSecSuccess, let code else { return false }
        return SecCodeCheckValidity(code, [], parsed) == errSecSuccess
    }

    func homeDirectory() -> String? {
        guard let entry = getpwuid(getuid()), let dir = entry.pointee.pw_dir else { return nil }
        let home = String(cString: dir)
        return home.hasPrefix("/") ? home : nil
    }

    func requestTrust() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        _ = CGRequestScreenCaptureAccess()
    }

    func resolvedPath(_ path: String) -> String? {
        guard let resolved = realpath(path, nil) else { return nil }
        defer { free(resolved) }
        return String(cString: resolved)
    }

    func window(id: UInt32) -> WindowInfo? {
        windowList([.optionIncludingWindow], CGWindowID(id)).first.flatMap(windowInfo)
    }

    /// The bound process's focused element, not the system-wide one. "No focused
    /// element" is not secure; any other AX failure is unknown (nil → secure).
    func focusedElementIsSecure(pid: Int) -> Bool? {
        let app = AXUIElementCreateApplication(pid_t(pid))
        var focused: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(app, kAXFocusedUIElementAttribute as CFString, &focused)
        if status == .noValue { return false }
        guard status == .success, let element = focused, CFGetTypeID(element) == AXUIElementGetTypeID() else {
            return nil
        }
        let ax = element as! AXUIElement // type id checked above
        return [kAXRoleAttribute, kAXSubroleAttribute].contains { attribute in
            var value: CFTypeRef?
            AXUIElementCopyAttributeValue(ax, attribute as CFString, &value)
            return (value as? String) == kAXSecureTextFieldSubrole as String
        }
    }

    /// From the window's real close button when AX can find it; else 28 pt.
    func titleBarHeight(window: WindowInfo) -> Double {
        guard let pid = windowList([.optionIncludingWindow], CGWindowID(window.id)).first?[kCGWindowOwnerPID as String]
            as? pid_t else { return defaultTitleBarHeight }
        let app = AXUIElementCreateApplication(pid)
        var windows: CFTypeRef?
        guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &windows) == .success,
              let list = windows as? [AXUIElement] else { return defaultTitleBarHeight }
        for candidate in list where frame(candidate).map({ near($0.origin, window.bounds) }) == true {
            var button: CFTypeRef?
            guard AXUIElementCopyAttributeValue(candidate, kAXCloseButtonAttribute as CFString, &button) == .success,
                  let close = button, CFGetTypeID(close) == AXUIElementGetTypeID(),
                  let closeFrame = frame(close as! AXUIElement) // type id checked above
            else { continue }
            return max(defaultTitleBarHeight, closeFrame.maxY - window.bounds.y + titleBarMargin)
        }
        return defaultTitleBarHeight
    }

    func capture(window: WindowInfo, maxEdge: Int) throws -> CapturedImage {
        let done = DispatchSemaphore(value: 0)
        var outcome: Result<CGImage, Error> = .failure(CaptureError("capture timed out"))
        Task {
            do {
                let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                guard let target = content.windows.first(where: { $0.windowID == window.id }) else {
                    throw CaptureError("the window is not shareable")
                }
                let filter = SCContentFilter(desktopIndependentWindow: target)
                let scale = Double(filter.pointPixelScale)
                let width = Double(target.frame.width) * scale
                let height = Double(target.frame.height) * scale
                let fit = min(1, Double(maxEdge) / max(width, height, 1))
                let config = SCStreamConfiguration()
                config.width = max(1, Int(width * fit))
                config.height = max(1, Int(height * fit))
                config.showsCursor = false
                config.ignoreShadowsSingleWindow = true // the image must be exactly the window
                outcome = .success(try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config))
            } catch {
                outcome = .failure(error)
            }
            done.signal()
        }
        guard done.wait(timeout: .now() + captureTimeout) == .success else { throw CaptureError("capture timed out") }
        let image = try outcome.get()
        return CapturedImage(png: try png(image), imageWidth: image.width, imageHeight: image.height)
    }

    func topWindow(at point: Point) -> UInt32? {
        // Front-to-back, every layer (menus, floating panels, Solus's own
        // windows): the first visible window containing the point is the one a
        // click would hit. Fully transparent windows are not hit.
        let probe = CGPoint(x: point.x, y: point.y)
        return windowList([.optionOnScreenOnly], kCGNullWindowID).first { entry in
            guard (entry[kCGWindowAlpha as String] as? Double ?? 1) > 0,
                  let dict = entry[kCGWindowBounds as String] as? NSDictionary,
                  let rect = CGRect(dictionaryRepresentation: dict as CFDictionary)
            else { return false }
            return rect.contains(probe)
        }.flatMap { $0[kCGWindowNumber as String] as? UInt32 }
    }

    func post(_ event: SyntheticEvent, toPid pid: Int?) {
        switch event {
        case .sleep(let ms):
            usleep(useconds_t(ms) * 1_000)
            return
        case .text(let text):
            // Unicode text in small chunks (one key-down/up pair each), split on
            // character boundaries so a surrogate pair or emoji is never cut.
            for chunk in textChunks(text) {
                for down in [true, false] {
                    let e = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down)
                    e?.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
                    send(e, toPid: pid)
                }
            }
            return
        default:
            send(cgEvent(for: event), toPid: pid)
        }
    }

    // MARK: private

    private func cgEvent(for event: SyntheticEvent) -> CGEvent? {
        func mouse(_ type: CGEventType, _ p: Point, _ button: CGMouseButton = .left) -> CGEvent? {
            CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: CGPoint(x: p.x, y: p.y),
                    mouseButton: button)
        }
        switch event {
        case .mouseMove(let p): return mouse(.mouseMoved, p)
        case .mouseDrag(let p): return mouse(.leftMouseDragged, p)
        case .mouseDown(let b, let p, let clicks):
            let e = b == .left ? mouse(.leftMouseDown, p) : mouse(.rightMouseDown, p, .right)
            e?.setIntegerValueField(.mouseEventClickState, value: Int64(clicks))
            return e
        case .mouseUp(let b, let p, let clicks):
            let e = b == .left ? mouse(.leftMouseUp, p) : mouse(.rightMouseUp, p, .right)
            e?.setIntegerValueField(.mouseEventClickState, value: Int64(clicks))
            return e
        case .scroll(let at, let dx, let dy):
            let e = CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 2,
                            wheel1: Int32(dy), wheel2: Int32(dx), wheel3: 0)
            e?.location = CGPoint(x: at.x, y: at.y) // the hit-tested point, not wherever the cursor is
            return e
        case .keyDown(let code, let modifiers), .keyUp(let code, let modifiers):
            let down: Bool
            if case .keyDown = event { down = true } else { down = false }
            let e = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(code), keyDown: down)
            e?.flags = flags(modifiers)
            return e
        case .text, .sleep:
            return nil
        }
    }

    /// Keyboard and text go straight to the bound process, so a focus change
    /// between the check and the post cannot redirect a keystroke.
    private func send(_ event: CGEvent?, toPid pid: Int?) {
        guard let event else { return }
        event.setIntegerValueField(.eventSourceUserData, value: solusEventMarker)
        if let pid { event.postToPid(pid_t(pid)) } else { event.post(tap: .cghidEventTap) }
        usleep(interEventMicros)
    }

    private func flags(_ modifiers: Set<Modifier>) -> CGEventFlags {
        var flags: CGEventFlags = []
        if modifiers.contains(.command) { flags.insert(.maskCommand) }
        if modifiers.contains(.shift) { flags.insert(.maskShift) }
        if modifiers.contains(.option) { flags.insert(.maskAlternate) }
        if modifiers.contains(.control) { flags.insert(.maskControl) }
        return flags
    }

    private func windowList(_ options: CGWindowListOption, _ relativeTo: CGWindowID) -> [[String: Any]] {
        (CGWindowListCopyWindowInfo(options, relativeTo) as? [[String: Any]]) ?? []
    }

    private func windowInfo(_ entry: [String: Any]) -> WindowInfo? {
        guard let number = entry[kCGWindowNumber as String] as? UInt32,
              let pid = entry[kCGWindowOwnerPID as String] as? pid_t,
              let boundsDict = entry[kCGWindowBounds as String] as? NSDictionary,
              let rect = CGRect(dictionaryRepresentation: boundsDict as CFDictionary)
        else { return nil }
        return WindowInfo(
            id: number,
            title: entry[kCGWindowName as String] as? String ?? "",
            bounds: Rect(x: rect.minX, y: rect.minY, width: rect.width, height: rect.height),
            ownerBundleId: NSRunningApplication(processIdentifier: pid)?.bundleIdentifier ?? "",
            ownerPid: Int(pid),
            onScreen: entry[kCGWindowIsOnscreen as String] as? Bool ?? false)
    }

    private func textChunks(_ text: String) -> [[UniChar]] {
        var chunks: [[UniChar]] = []
        var current: [UniChar] = []
        for character in text {
            let units = Array(String(character).utf16)
            if !current.isEmpty, current.count + units.count > 16 {
                chunks.append(current)
                current = []
            }
            current += units
        }
        if !current.isEmpty { chunks.append(current) }
        return chunks
    }

    private func frame(_ element: AXUIElement) -> CGRect? {
        var position: CFTypeRef?
        var size: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &position) == .success,
              AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &size) == .success,
              let p = position, let s = size else { return nil }
        var origin = CGPoint.zero
        var extent = CGSize.zero
        guard AXValueGetValue(p as! AXValue, .cgPoint, &origin), // AX position/size are AXValues
              AXValueGetValue(s as! AXValue, .cgSize, &extent) else { return nil }
        return CGRect(origin: origin, size: extent)
    }

    private func near(_ origin: CGPoint, _ bounds: Rect) -> Bool {
        abs(origin.x - bounds.x) < 2 && abs(origin.y - bounds.y) < 2
    }

    private func png(_ image: CGImage) throws -> Data {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil)
        else { throw CaptureError("png encoder unavailable") }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { throw CaptureError("png encoding failed") }
        return data as Data
    }
}
