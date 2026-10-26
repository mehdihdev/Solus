// `solus-input` commands (sol-drive.md §2). Every check runs BEFORE any event
// is planned or posted; a refusal posts nothing. Output is exactly one JSON line.
import Foundation

public struct Refusal: Error, Equatable {
    public let code: String
    public let message: String
    /// Set when the refusal came mid-verb (`focus_lost`): how many events landed.
    public var postedEvents: Int?
}

private func refuse(_ code: String, _ message: String) -> Refusal { Refusal(code: code, message: message) }

/// A verb's validated plan: the events to post, in window-relative points.
private struct Plan {
    let verb: String
    let events: (Rect) -> [SyntheticEvent]
    let isTyping: Bool
}

public struct Runner {
    public static let defaultMaxEdge = 1568
    static let maxTextLength = 200
    static let maxWaitMs = 2000
    static let maxScroll = 50
    static let dragSteps = 10
    /// Our own previous action may land a hair after the `since` stamp.
    static let ownActionSlack = 0.05
    /// `--since` older than this is a stale or forged stamp, not a step in progress.
    static let maxSinceAge = 600.0

    let port: SystemPort

    public init(port: SystemPort) { self.port = port }

    public func run(_ argv: [String]) -> String {
        let result: Result<[String: Any], Refusal>
        if let args = Arguments(argv) {
            switch args.command {
            case "identify": result = identify(args)
            case "capture": result = capture(args)
            case "act": result = act(args)
            default: result = .failure(refuse("usage", "unknown command"))
            }
        } else {
            result = .failure(refuse("usage", "malformed arguments"))
        }
        switch result {
        case .success(let body): return encode(["ok": true].merging(body) { $1 })
        case .failure(let refusal):
            var body: [String: Any] = ["ok": false, "code": refusal.code, "message": refusal.message]
            if let posted = refusal.postedEvents { body["postedEvents"] = posted }
            return encode(body)
        }
    }

    // MARK: identify

    private func identify(_ args: Arguments) -> Result<[String: Any], Refusal> {
        guard args.verb == nil, args.has(only: []) else { return .failure(refuse("usage", "identify takes no arguments")) }
        let front = port.frontmost()
        let trust: [String: Any] = [
            "accessibility": port.accessibilityTrusted(),
            "screenRecording": port.screenRecordingAllowed(),
        ]
        // `now` is the helper's clock: the caller passes it back as `--since`, so
        // the kill switch never compares across machines (cloud vs local).
        guard let front else {
            return .success(["app": NSNull(), "window": NSNull(), "trust": trust, "allowed": false, "now": port.now()])
        }
        return .success([
            "now": port.now(),
            "app": ["bundleId": front.app.bundleId, "pid": front.app.pid, "name": front.app.name],
            "window": front.window.map(Self.windowJSON) ?? NSNull(),
            "trust": trust,
            "allowed": DrivableApps.allows(front.app.bundleId),
        ])
    }

    static func windowJSON(_ window: WindowInfo) -> [String: Any] {
        [
            "id": Int(window.id),
            "title": window.title,
            "bounds": [
                "x": Int(window.bounds.x.rounded()), "y": Int(window.bounds.y.rounded()),
                "width": Int(window.bounds.width.rounded()), "height": Int(window.bounds.height.rounded()),
            ],
        ]
    }

    // MARK: capture

    private func capture(_ args: Arguments) -> Result<[String: Any], Refusal> {
        guard args.verb == nil, args.has(only: ["bundle", "window", "max-edge"]),
              let bundle = args.string("bundle"), let windowId = args.windowId("window")
        else { return .failure(refuse("usage", "capture --bundle B --window W [--max-edge N]")) }
        let maxEdge = args.string("max-edge") == nil ? Self.defaultMaxEdge : (args.int("max-edge") ?? -1)
        guard (256...4096).contains(maxEdge) else { return .failure(refuse("usage", "max-edge must be 256-4096")) }
        guard DrivableApps.allows(bundle) else { return .failure(refuse("app_not_allowed", "not a drivable app")) }
        guard port.screenRecordingAllowed() else {
            return .failure(refuse("screen_recording_denied", "Screen Recording is not granted"))
        }
        guard let window = port.window(id: windowId), window.onScreen else {
            return .failure(refuse("window_not_found", "no such on-screen window"))
        }
        guard window.ownerBundleId == bundle else {
            return .failure(refuse("window_mismatch", "the window belongs to another app"))
        }
        do {
            let image = try port.capture(window: window, maxEdge: maxEdge)
            return .success([
                "png": image.png.base64EncodedString(),
                "imageWidth": image.imageWidth, "imageHeight": image.imageHeight,
                "pointsWidth": Int(window.bounds.width.rounded()),
                "pointsHeight": Int(window.bounds.height.rounded()),
            ])
        } catch let error as CaptureError {
            return .failure(refuse("capture_failed", error.message))
        } catch {
            return .failure(refuse("capture_failed", "capture failed"))
        }
    }

    // MARK: act

    private func act(_ args: Arguments) -> Result<[String: Any], Refusal> {
        guard let bundle = args.string("bundle"), let windowId = args.windowId("window"),
              let since = args.double("since"), let verb = args.verb
        else { return .failure(refuse("usage", "act --bundle B --window W --since T <verb> ...")) }
        let plan: Plan
        switch Self.plan(verb, args) {
        case .success(let p): plan = p
        case .failure(let refusal): return .failure(refusal)
        }
        guard DrivableApps.allows(bundle) else { return .failure(refuse("app_not_allowed", "not a drivable app")) }
        guard port.accessibilityTrusted() else {
            return .failure(refuse("not_trusted", "Accessibility is not granted to Solus"))
        }
        guard let front = port.frontmost(), front.app.bundleId == bundle else {
            return .failure(refuse("not_frontmost", "the bound app is not in front"))
        }
        guard let window = front.window, window.id == windowId else {
            return .failure(refuse("window_mismatch", "the bound window is not in front"))
        }
        let now = port.now()
        guard since.isFinite, since <= now + Self.ownActionSlack, now - since <= Self.maxSinceAge else {
            return .failure(refuse("usage", "--since must be a recent time from this helper's clock"))
        }
        let events = plan.events(window.bounds)
        if let outside = Self.firstOutside(events, window.bounds) { return .failure(outside) }
        if let covered = firstOccluded(events, window.id) { return .failure(covered) }
        if plan.isTyping, port.focusedElementIsSecure() {
            return .failure(refuse("secure_field", "a password field has focus"))
        }
        let idle = port.secondsSinceLastPhysicalInput()
        if now - idle > since + Self.ownActionSlack {
            return .failure(refuse("user_active", "you used the mouse or keyboard; SOL stopped"))
        }
        if let lost = post(events, bundle: bundle, windowId: windowId, pid: front.app.pid) { return .failure(lost) }
        return .success(["verb": plan.verb, "idleSeconds": idle, "finishedAt": port.now()])
    }

    /// Each pointer target must be the bound window itself, not something on top
    /// of it — Solus's own windows included (SOL must never click its own Run).
    private func firstOccluded(_ events: [SyntheticEvent], _ windowId: UInt32) -> Refusal? {
        for event in events {
            if let p = Self.pointerTarget(event), port.topWindow(at: p) != windowId {
                return refuse("occluded", "another window covers that point")
            }
        }
        return nil
    }

    /// Post in order, re-checking before EVERY event that the bound app and
    /// window are still in front; keys and text go to the bound process only.
    private func post(_ events: [SyntheticEvent], bundle: String, windowId: UInt32, pid: Int) -> Refusal? {
        for (index, event) in events.enumerated() {
            guard let front = port.frontmost(), front.app.bundleId == bundle, front.window?.id == windowId else {
                var lost = refuse("focus_lost", "the bound window lost focus; SOL stopped")
                lost.postedEvents = index
                return lost
            }
            port.post(event, toPid: Self.pointerTarget(event) == nil && !Self.isPause(event) ? pid : nil)
        }
        return nil
    }

    private static func isPause(_ event: SyntheticEvent) -> Bool {
        if case .sleep = event { return true }
        return false
    }

    private static func pointerTarget(_ event: SyntheticEvent) -> Point? {
        switch event {
        case .mouseMove(let p), .mouseDrag(let p), .mouseDown(_, let p, _), .mouseUp(_, let p, _): return p
        default: return nil
        }
    }

    /// Every pointer event must land inside the window it is bound to.
    private static func firstOutside(_ events: [SyntheticEvent], _ bounds: Rect) -> Refusal? {
        for event in events {
            if let p = pointerTarget(event),
               p.x < bounds.x || p.y < bounds.y || p.x >= bounds.x + bounds.width || p.y >= bounds.y + bounds.height {
                return refuse("out_of_bounds", "the point is outside the bound window")
            }
        }
        return nil
    }

    private static func plan(_ verb: String, _ args: Arguments) -> Result<Plan, Refusal> {
        let common: Set<String> = ["bundle", "window", "since"]
        let usage = refuse("usage", "bad arguments for \(verb)")
        func point(_ xKey: String, _ yKey: String) -> (Int, Int)? {
            guard let x = args.int(xKey), let y = args.int(yKey) else { return nil }
            return (x, y)
        }
        func global(_ p: (Int, Int), _ b: Rect) -> Point { Point(x: b.x + Double(p.0), y: b.y + Double(p.1)) }
        switch verb {
        case "click":
            guard args.has(only: common.union(["x", "y", "button", "count"])), let p = point("x", "y"),
                  let button = MouseButton(rawValue: args.string("button") ?? "left"),
                  let count = args.string("count") == nil ? 1 : args.int("count"), (1...2).contains(count)
            else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in
                let at = global(p, b)
                return [.mouseMove(at)] + (1...count).flatMap { n in
                    [SyntheticEvent.mouseDown(button, at, clicks: n), .mouseUp(button, at, clicks: n)]
                }
            }, isTyping: false))
        case "move":
            guard args.has(only: common.union(["x", "y"])), let p = point("x", "y") else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in [.mouseMove(global(p, b))] }, isTyping: false))
        case "drag":
            guard args.has(only: common.union(["x", "y", "to-x", "to-y"])),
                  let from = point("x", "y"), let to = point("to-x", "to-y") else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in
                let start = global(from, b), end = global(to, b)
                let path = (1...dragSteps).map { i -> SyntheticEvent in
                    let t = Double(i) / Double(dragSteps)
                    return .mouseDrag(Point(x: start.x + (end.x - start.x) * t, y: start.y + (end.y - start.y) * t))
                }
                return [.mouseMove(start), .mouseDown(.left, start, clicks: 1)] + path + [.mouseUp(.left, end, clicks: 1)]
            }, isTyping: false))
        case "scroll":
            guard args.has(only: common.union(["x", "y", "dx", "dy"])), let p = point("x", "y"),
                  let dy = args.int("dy"), let dx = args.string("dx") == nil ? 0 : args.int("dx"),
                  abs(dx) <= maxScroll, abs(dy) <= maxScroll
            else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in [.mouseMove(global(p, b)), .scroll(dx: dx, dy: dy)] },
                                 isTyping: false))
        case "key":
            guard args.has(only: common.union(["chord"])), let text = args.string("chord") else { return .failure(usage) }
            guard let chord = Chord.parse(text), let code = KeyMap.code(for: chord.key) else {
                return .failure(refuse("bad_chord", "not a chord this helper knows"))
            }
            guard ChordPolicy.allows(chord) else { return .failure(refuse("chord_denied", "that shortcut is not allowed")) }
            return .success(Plan(verb: verb, events: { _ in
                [.keyDown(code, chord.modifiers), .keyUp(code, chord.modifiers)]
            }, isTyping: false))
        case "type":
            guard args.has(only: common.union(["text"])), let text = args.string("text") else { return .failure(usage) }
            guard (1...maxTextLength).contains(text.count),
                  !text.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
            else { return .failure(refuse("bad_text", "1-200 printable characters, no newlines")) }
            return .success(Plan(verb: verb, events: { _ in [.text(text)] }, isTyping: true))
        case "wait":
            guard args.has(only: common.union(["ms"])), let ms = args.int("ms"), (0...maxWaitMs).contains(ms)
            else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { _ in [.sleep(milliseconds: ms)] }, isTyping: false))
        default:
            return .failure(refuse("usage", "unknown verb"))
        }
    }

    private func encode(_ object: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes]),
              let line = String(data: data, encoding: .utf8)
        else { return #"{"code":"usage","message":"unencodable","ok":false}"# }
        return line
    }
}
