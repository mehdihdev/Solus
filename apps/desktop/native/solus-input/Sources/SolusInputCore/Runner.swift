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
    let isKeyboard: Bool
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
    /// Mid-verb, our own just-posted event lands within this of its post time;
    /// input later than that is the user (fails closed if delivery is slower).
    static let ownEventSlack = 0.003
    /// A capture's aspect may differ from the window's by rounding only.
    static let aspectTolerance = 0.02

    /// A release build answers any invocation but `serve` with this (sol-drive.md §2
    /// "Caller"); the build script checks it to prove the binary is not a debug one.
    public static let agentOnlyUsage =
        #"{"code":"usage","message":"solus-input runs only as the Solus agent (serve)","ok":false,"unsignedDev":false}"#

    let port: SystemPort
    /// Debug builds only (`SOLUS_INPUT_UNSIGNED_DEV`): reported, never a skip here.
    let unsignedDev: Bool

    /// Callers are authenticated before this (the agent, §2.1); debug argv runs are tests.
    public init(port: SystemPort, unsignedDev: Bool) { self.port = port; self.unsignedDev = unsignedDev }

    public func run(_ argv: [String]) -> String {
        let result: Result<[String: Any], Refusal>
        if argv.first == "trust" {
            result = trust(Array(argv.dropFirst()))
        } else if let args = Arguments(argv) {
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

    // MARK: trust

    /// Posts nothing and captures nothing. Through the agent only Solus.app may ask (§2.1).
    private func trust(_ options: [String]) -> Result<[String: Any], Refusal> {
        guard options.isEmpty || options == ["--prompt"] else { return .failure(refuse("usage", "trust [--prompt]")) }
        if !options.isEmpty { port.requestTrust() }
        return .success(["trust": trustJSON(), "unsignedDev": unsignedDev])
    }

    private func trustJSON() -> [String: Any] {
        ["accessibility": port.accessibilityTrusted(), "screenRecording": port.screenRecordingAllowed()]
    }

    // MARK: identify

    private func identify(_ args: Arguments) -> Result<[String: Any], Refusal> {
        guard args.verb == nil, args.has(only: ["within"]), let root = workspace(args) else {
            return .failure(refuse("usage", "identify --within WORKSPACE"))
        }
        let body = identifyBody(root)
        return .success(body.merging(["unsignedDev": unsignedDev]) { $1 })
    }

    private func identifyBody(_ root: String) -> [String: Any] {
        let front = port.frontmost()
        let trust = trustJSON()
        // `now` is the helper's clock: the caller passes it back as `--since`, so
        // the kill switch never compares across machines (cloud vs local).
        guard let front else {
            return ["app": NSNull(), "window": NSNull(), "trust": trust, "allowed": false, "now": port.now()]
        }
        // Another app's identity and window title never leave the machine.
        guard DrivableApps.allows(front.app.bundleId) else {
            return ["app": NSNull(), "window": NSNull(), "trust": trust, "allowed": false, "now": port.now()]
        }
        // A drivable app working on another project is hidden like any other app.
        guard worksInside(pid: front.app.pid, root) else {
            return [
                "app": NSNull(), "window": NSNull(), "trust": trust, "allowed": false,
                "outsideWorkspace": true, "now": port.now(),
            ]
        }
        return [
            "now": port.now(),
            "outsideWorkspace": false,
            "app": ["bundleId": front.app.bundleId, "pid": front.app.pid, "name": front.app.name],
            "window": front.window.map(Self.windowJSON) ?? NSNull(),
            "trust": trust,
            "allowed": true,
        ]
    }

    static func windowJSON(_ window: WindowInfo) -> [String: Any] {
        ["id": Int(window.id), "title": window.title, "bounds": boundsJSON(window.bounds)]
    }

    /// Global points, top-left origin — the desktop draws the amber outline from it.
    static func boundsJSON(_ bounds: Rect) -> [String: Int] {
        [
            "x": Int(bounds.x.rounded()), "y": Int(bounds.y.rounded()),
            "width": Int(bounds.width.rounded()), "height": Int(bounds.height.rounded()),
        ]
    }

    // MARK: capture

    private func capture(_ args: Arguments) -> Result<[String: Any], Refusal> {
        guard args.verb == nil, args.has(only: ["bundle", "window", "max-edge", "within"]),
              let bundle = args.string("bundle"), let windowId = args.windowId("window"), let root = workspace(args)
        else { return .failure(refuse("usage", "capture --bundle B --window W --within WORKSPACE [--max-edge N]")) }
        let maxEdge = args.string("max-edge") == nil ? Self.defaultMaxEdge : (args.int("max-edge") ?? -1)
        guard (256...2048).contains(maxEdge) else { return .failure(refuse("usage", "max-edge must be 256-2048")) }
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
        guard worksInside(pid: window.ownerPid, root) else { return .failure(outsideWorkspace) }
        do {
            let image = try port.capture(window: window, maxEdge: maxEdge)
            // A padded image (a window shadow) would skew every coordinate mapped from it.
            let imageAspect = Double(image.imageWidth) / Double(max(image.imageHeight, 1))
            let windowAspect = window.bounds.width / max(window.bounds.height, 1)
            guard abs(imageAspect - windowAspect) <= Self.aspectTolerance * windowAspect else {
                return .failure(refuse("capture_failed", "the capture does not match the window's shape"))
            }
            return .success([
                "png": image.png.base64EncodedString(),
                "imageWidth": image.imageWidth, "imageHeight": image.imageHeight,
                "pointsWidth": Int(window.bounds.width.rounded()),
                "pointsHeight": Int(window.bounds.height.rounded()),
                "bounds": Self.boundsJSON(window.bounds),
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
              let since = args.double("since"), let verb = args.verb, let root = workspace(args)
        else { return .failure(refuse("usage", "act --bundle B --window W --since T --within WORKSPACE <verb> ...")) }
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
        guard worksInside(pid: front.app.pid, root) else { return .failure(outsideWorkspace) }
        let now = port.now()
        guard since.isFinite, since <= now + Self.ownActionSlack, now - since <= Self.maxSinceAge else {
            return .failure(refuse("usage", "--since must be a recent time from this helper's clock"))
        }
        if let resized = Self.resized(args, window.bounds) { return .failure(resized) }
        let events = plan.events(window.bounds)
        if let outside = Self.firstOutside(events, window.bounds) { return .failure(outside) }
        if let chrome = Self.firstOnChrome(events, window.bounds, port.titleBarHeight(window: window)) {
            return .failure(chrome)
        }
        if let covered = firstOccluded(events, window.id) { return .failure(covered) }
        if plan.isKeyboard, port.focusedElementIsSecure(pid: front.app.pid) != false {
            return .failure(refuse("secure_field", "a password field has focus, or focus could not be read"))
        }
        let idle = port.secondsSinceLastPhysicalInput()
        if now - idle > since + Self.ownActionSlack {
            return .failure(refuse("user_active", "you used the mouse or keyboard; SOL stopped"))
        }
        if let lost = post(events, bundle: bundle, windowId: windowId, pid: front.app.pid, root: root) {
            return .failure(lost)
        }
        let bounds = port.window(id: windowId)?.bounds ?? window.bounds // re-read: the step may have moved it
        return .success([
            "verb": plan.verb, "idleSeconds": idle, "finishedAt": port.now(), "bounds": Self.boundsJSON(bounds),
        ])
    }

    // MARK: project binding (ADR-041 amendment, M2)

    /// `--within W`: the linked workspace — absolute, resolved, never the whole
    /// disk, the home directory or any folder above it (unreadable home fails closed).
    private func workspace(_ args: Arguments) -> String? {
        guard let raw = args.string("within"), raw.hasPrefix("/"), let root = port.resolvedPath(raw), root != "/",
              let home = port.homeDirectory().flatMap(port.resolvedPath), !Self.isAtOrAbove(root, home)
        else { return nil }
        return root
    }

    /// `path` equals `other` or is one of its ancestors — by bytes, whole segments.
    static func isAtOrAbove(_ path: String, _ other: String) -> Bool {
        let base = Array(path.utf8), target = Array(other.utf8)
        return target == base || target.starts(with: base + Array("/".utf8))
    }

    /// The process works in `root` or below it; unreadable counts as outside.
    private func worksInside(pid: Int, _ root: String) -> Bool {
        // Bytes, not Swift string equality (which treats NFC and NFD as equal).
        guard let dir = port.workingDirectory(pid: pid) else { return false }
        return Self.isAtOrAbove(root, dir)
    }

    /// No path in the message: another project's location never leaves the machine.
    private var outsideWorkspace: Refusal {
        refuse("outside_workspace", "KiCad in front has a project outside this Solus project open")
    }

    /// `--expect-width/--expect-height`: the size the caller captured. A resize
    /// since then would land a remapped click on a different control.
    private static func resized(_ args: Arguments, _ bounds: Rect) -> Refusal? {
        let width = args.string("expect-width") == nil ? nil : args.int("expect-width") ?? -1
        let height = args.string("expect-height") == nil ? nil : args.int("expect-height") ?? -1
        if let width, width != Int(bounds.width.rounded()) { return refuse("window_resized", "the window changed size") }
        if let height, height != Int(bounds.height.rounded()) { return refuse("window_resized", "the window changed size") }
        return nil
    }

    /// The title bar holds close / minimise / zoom (and double-click zooms):
    /// closing needs its own approval (ADR-041 §4), so no pointer target lands there.
    private static func firstOnChrome(_ events: [SyntheticEvent], _ bounds: Rect, _ titleBar: Double) -> Refusal? {
        for event in events {
            if let p = pointerTarget(event), p.y < bounds.y + titleBar {
                return refuse("window_chrome", "that point is on the window's title bar")
            }
        }
        return nil
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

    /// Post in order. Before EVERY event: no stop signal, the bound app and window
    /// still in front, still working inside the workspace, no physical input since our previous post, and — for a
    /// pointer event — nothing opened over its target since. Keys, text and
    /// pauses go to the bound process (or nowhere); pointer events post globally.
    /// A stop with a button held releases it — globally while the press point is
    /// still over the bound window (the window server tracks the button there),
    /// otherwise to the bound process only (a global release over a popup menu
    /// would choose an item in it).
    private func post(_ events: [SyntheticEvent], bundle: String, windowId: UInt32, pid: Int, root: String) -> Refusal? {
        var held: (MouseButton, Point)?
        var lastPost: Double?
        for (index, event) in events.enumerated() {
            if var stop = stopReason(event, bundle: bundle, windowId: windowId, lastPost: lastPost)
                ?? (worksInside(pid: pid, root) ? nil : outsideWorkspace) {
                if let (button, at) = held {
                    port.post(.mouseUp(button, at, clicks: 1), toPid: port.topWindow(at: at) == windowId ? nil : pid)
                }
                stop.postedEvents = index
                return stop
            }
            lastPost = port.now()
            port.post(event, toPid: Self.pointerTarget(event) == nil && !Self.isPause(event) ? pid : nil)
            switch event {
            case .mouseDown(let button, let at, _): held = (button, at)
            case .mouseUp: held = nil
            case .mouseDrag(let at): held = held.map { ($0.0, at) }
            default: break
            }
        }
        return nil
    }

    private func stopReason(_ event: SyntheticEvent, bundle: String, windowId: UInt32, lastPost: Double?) -> Refusal? {
        if port.stopRequested() { return refuse("stopped", "SOL was stopped") }
        guard let front = port.frontmost(), front.app.bundleId == bundle, front.window?.id == windowId else {
            return refuse("focus_lost", "the bound window lost focus; SOL stopped")
        }
        if let lastPost, port.now() - port.secondsSinceLastPhysicalInput() > lastPost + Self.ownEventSlack {
            return refuse("user_active", "you used the mouse or keyboard; SOL stopped")
        }
        if let p = Self.pointerTarget(event), port.topWindow(at: p) != windowId {
            return refuse("occluded", "something opened over that point; SOL stopped")
        }
        return nil
    }

    private static func isPause(_ event: SyntheticEvent) -> Bool {
        if case .sleep = event { return true }
        return false
    }

    private static func pointerTarget(_ event: SyntheticEvent) -> Point? {
        switch event {
        case .mouseMove(let p), .mouseDrag(let p), .mouseDown(_, let p, _), .mouseUp(_, let p, _), .scroll(let p, _, _):
            return p
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
        let common: Set<String> = ["bundle", "window", "since", "expect-width", "expect-height", "within"]
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
                  let count = args.string("count") == nil ? 1 : args.int("count"), (1...2).contains(count),
                  button == .left || count == 1 // a right click opens a menu; never click it twice
            else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in
                let at = global(p, b)
                return [.mouseMove(at)] + (1...count).flatMap { n in
                    [SyntheticEvent.mouseDown(button, at, clicks: n), .mouseUp(button, at, clicks: n)]
                }
            }, isKeyboard: false))
        case "move":
            guard args.has(only: common.union(["x", "y"])), let p = point("x", "y") else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in [.mouseMove(global(p, b))] }, isKeyboard: false))
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
            }, isKeyboard: false))
        case "scroll":
            guard args.has(only: common.union(["x", "y", "dx", "dy"])), let p = point("x", "y"),
                  let dy = args.int("dy"), let dx = args.string("dx") == nil ? 0 : args.int("dx"),
                  abs(dx) <= maxScroll, abs(dy) <= maxScroll
            else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { b in
                let at = global(p, b)
                return [.mouseMove(at), .scroll(at, dx: dx, dy: dy)]
            }, isKeyboard: false))
        case "key":
            guard args.has(only: common.union(["chord"])), let text = args.string("chord") else { return .failure(usage) }
            guard let chord = Chord.parse(text), let code = KeyMap.code(for: chord.key) else {
                return .failure(refuse("bad_chord", "not a chord this helper knows"))
            }
            guard ChordPolicy.allows(chord) else { return .failure(refuse("chord_denied", "that shortcut is not allowed")) }
            return .success(Plan(verb: verb, events: { _ in
                [.keyDown(code, chord.modifiers), .keyUp(code, chord.modifiers)]
            }, isKeyboard: true))
        case "type":
            guard args.has(only: common.union(["text"])), let text = args.string("text") else { return .failure(usage) }
            guard (1...maxTextLength).contains(text.unicodeScalars.count),
                  text.unicodeScalars.allSatisfy(Self.isVisibleText)
            else { return .failure(refuse("bad_text", "1-200 visible characters, no newlines or control characters")) }
            return .success(Plan(verb: verb, events: { _ in [.text(text)] }, isKeyboard: true))
        case "wait":
            guard args.has(only: common.union(["ms"])), let ms = args.int("ms"), (0...maxWaitMs).contains(ms)
            else { return .failure(usage) }
            return .success(Plan(verb: verb, events: { _ in [.sleep(milliseconds: ms)] }, isKeyboard: false))
        default:
            return .failure(refuse("usage", "unknown verb"))
        }
    }

    /// Letters, marks, numbers, punctuation, symbols and the space separator —
    /// never control/format/private-use (U+F704 is Cocoa's F1) or line separators.
    static let visibleText: CharacterSet = CharacterSet.letters
        .union(.decimalDigits).union(.nonBaseCharacters).union(.punctuationCharacters).union(.symbols)
        .union(CharacterSet(charactersIn: " "))
        .union(CharacterSet(charactersIn: UnicodeScalar(0x2150)!...UnicodeScalar(0x218F)!)) // number forms
    static func isVisibleText(_ scalar: Unicode.Scalar) -> Bool {
        visibleText.contains(scalar) && !(0xE000...0xF8FF).contains(scalar.value)
    }

    private func encode(_ object: [String: Any]) -> String {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes]),
              let line = String(data: data, encoding: .utf8)
        else { return #"{"code":"usage","message":"unencodable","ok":false}"# }
        return line
    }
}
