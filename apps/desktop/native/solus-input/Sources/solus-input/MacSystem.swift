// The real `SystemPort`: Accessibility, CoreGraphics event posting and window
// lists, ScreenCaptureKit capture. Kept thin — every decision is in
// SolusInputCore.Runner, which is unit-tested against a fake of this.
import AppKit
import ApplicationServices
import CoreGraphics
import ImageIO
import ScreenCaptureKit
import SolusInputCore
import UniformTypeIdentifiers

/// Stamped into `eventSourceUserData` on every event we post ("SOLUS").
let solusEventMarker: Int64 = 0x534F_4C55_53
/// A short gap between posted events so the target app sees each one.
let interEventMicros: useconds_t = 8_000
let captureTimeout: DispatchTimeInterval = .seconds(10)
/// HID event types that count as the user touching the machine.
let physicalInputTypes: [CGEventType] = [
    .mouseMoved, .leftMouseDown, .rightMouseDown, .otherMouseDown, .leftMouseDragged,
    .rightMouseDragged, .scrollWheel, .keyDown, .flagsChanged,
]

struct MacSystem: SystemPort {
    private let source = CGEventSource(stateID: .privateState)

    func accessibilityTrusted() -> Bool { AXIsProcessTrusted() }
    func screenRecordingAllowed() -> Bool { CGPreflightScreenCaptureAccess() }
    func now() -> Double { Date().timeIntervalSince1970 }

    func secondsSinceLastPhysicalInput() -> Double {
        physicalInputTypes
            .map { CGEventSource.secondsSinceLastEventType(.hidSystemState, eventType: $0) }
            .min() ?? .greatestFiniteMagnitude
    }

    func frontmost() -> FrontmostInfo? {
        guard let app = NSWorkspace.shared.frontmostApplication, let bundle = app.bundleIdentifier else { return nil }
        let pid = app.processIdentifier
        let front = windowList([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            .first { ($0[kCGWindowOwnerPID as String] as? pid_t) == pid && ($0[kCGWindowLayer as String] as? Int) == 0 }
        return FrontmostInfo(
            app: AppInfo(bundleId: bundle, pid: Int(pid), name: app.localizedName ?? bundle),
            window: front.flatMap(windowInfo))
    }

    func window(id: UInt32) -> WindowInfo? {
        windowList([.optionIncludingWindow], CGWindowID(id)).first.flatMap(windowInfo)
    }

    func focusedElementIsSecure() -> Bool {
        let system = AXUIElementCreateSystemWide()
        var focused: CFTypeRef?
        guard AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
              let element = focused, CFGetTypeID(element) == AXUIElementGetTypeID()
        else { return false }
        let ax = element as! AXUIElement // swiftlint:disable:this force_cast — type id checked above
        return [kAXRoleAttribute, kAXSubroleAttribute].contains { attribute in
            var value: CFTypeRef?
            AXUIElementCopyAttributeValue(ax, attribute as CFString, &value)
            return (value as? String) == "AXSecureTextField"
        }
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

    func post(_ event: SyntheticEvent) {
        switch event {
        case .sleep(let ms):
            usleep(useconds_t(ms) * 1_000)
            return
        case .text(let text):
            // Unicode text in small chunks: one key-down/up pair per chunk.
            let units = Array(text.utf16)
            stride(from: 0, to: units.count, by: 16).forEach { start in
                let chunk = Array(units[start..<min(start + 16, units.count)])
                for down in [true, false] {
                    let e = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down)
                    e?.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
                    send(e)
                }
            }
            return
        default:
            send(cgEvent(for: event))
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
        case .scroll(let dx, let dy):
            return CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 2,
                           wheel1: Int32(dy), wheel2: Int32(dx), wheel3: 0)
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

    private func send(_ event: CGEvent?) {
        guard let event else { return }
        event.setIntegerValueField(.eventSourceUserData, value: solusEventMarker)
        event.post(tap: .cghidEventTap)
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
            onScreen: entry[kCGWindowIsOnscreen as String] as? Bool ?? false)
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
