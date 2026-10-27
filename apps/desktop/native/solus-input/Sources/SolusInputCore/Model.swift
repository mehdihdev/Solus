// The values `Runner` reasons over, and the one seam to the operating system.
// Coordinates are global points (top-left origin), as CoreGraphics reports
// window bounds and posts mouse events.
import Foundation

public struct Point: Equatable {
    public let x: Double
    public let y: Double
    public init(x: Double, y: Double) { self.x = x; self.y = y }
}

public struct Rect: Equatable {
    public let x: Double
    public let y: Double
    public let width: Double
    public let height: Double
    public init(x: Double, y: Double, width: Double, height: Double) {
        self.x = x; self.y = y; self.width = width; self.height = height
    }
}

public struct AppInfo: Equatable {
    public let bundleId: String
    public let pid: Int
    public let name: String
    public init(bundleId: String, pid: Int, name: String) {
        self.bundleId = bundleId; self.pid = pid; self.name = name
    }
}

public struct WindowInfo: Equatable {
    public let id: UInt32
    public let title: String
    public let bounds: Rect
    public let ownerBundleId: String
    public let ownerPid: Int
    public let onScreen: Bool
    public init(id: UInt32, title: String, bounds: Rect, ownerBundleId: String, ownerPid: Int, onScreen: Bool) {
        self.id = id; self.title = title; self.bounds = bounds
        self.ownerBundleId = ownerBundleId; self.ownerPid = ownerPid; self.onScreen = onScreen
    }
}

/// The frontmost app and its frontmost ordinary (layer 0) window, read fresh.
public struct FrontmostInfo: Equatable {
    public let app: AppInfo
    public let window: WindowInfo?
    public init(app: AppInfo, window: WindowInfo?) { self.app = app; self.window = window }
}

public struct CapturedImage: Equatable {
    public let png: Data
    public let imageWidth: Int
    public let imageHeight: Int
    public init(png: Data, imageWidth: Int, imageHeight: Int) {
        self.png = png; self.imageWidth = imageWidth; self.imageHeight = imageHeight
    }
}

public enum MouseButton: String, Equatable {
    case left
    case right
}

public enum Modifier: String, Hashable, CaseIterable {
    case command
    case shift
    case option
    case control
}

/// One event the helper posts. `sleep` is a pause inside a verb (`wait`).
public enum SyntheticEvent: Equatable {
    case mouseMove(Point)
    case mouseDown(MouseButton, Point, clicks: Int)
    case mouseUp(MouseButton, Point, clicks: Int)
    case mouseDrag(Point)
    case scroll(Point, dx: Int, dy: Int)
    case keyDown(UInt16, Set<Modifier>)
    case keyUp(UInt16, Set<Modifier>)
    case text(String)
    case sleep(milliseconds: Int)
}

public struct CaptureError: Error {
    public let message: String
    public init(_ message: String) { self.message = message }
}

/// Everything `Runner` needs from macOS. The real one lives in the executable;
/// tests use a fake.
public protocol SystemPort {
    func accessibilityTrusted() -> Bool
    func screenRecordingAllowed() -> Bool
    func frontmost() -> FrontmostInfo?
    func window(id: UInt32) -> WindowInfo?
    /// Whether the bound process's focused element is a password field; nil when
    /// it cannot be read (the caller treats unknown as secure).
    func focusedElementIsSecure(pid: Int) -> Bool?
    /// Height of the window's title bar (close/minimise/zoom live there), points.
    func titleBarHeight(window: WindowInfo) -> Double
    /// Seconds since the HID system last saw input (any device).
    func secondsSinceLastPhysicalInput() -> Double
    /// A monotonic clock, seconds (system uptime) — the `--since` clock.
    func now() -> Double
    /// SIGTERM arrived: stop between events and release anything held.
    func stopRequested() -> Bool
    func capture(window: WindowInfo, maxEdge: Int) throws -> CapturedImage
    /// The id of the topmost visible on-screen window containing `point`, any layer.
    func topWindow(at point: Point) -> UInt32?
    /// The process's current working directory, resolved; nil when unreadable.
    /// KiCad works in its open project's folder.
    func workingDirectory(pid: Int) -> String?
    /// `realpath`; nil when the path does not resolve.
    func resolvedPath(_ path: String) -> String?
    /// `getppid()`.
    func ownParentPid() -> Int
    /// The kernel's parent pid of `pid`; nil when unreadable.
    func parentPid(of pid: Int) -> Int?
    /// `argc` of `pid` (`KERN_PROCARGS2`); nil when unreadable.
    func argumentCount(pid: Int) -> Int?
    /// The code-signing service says `pid` satisfies `requirement`.
    func satisfies(pid: Int, requirement: String) -> Bool
    /// The helper's own signature checks out.
    func ownSignatureIsValid() -> Bool
    /// Ask macOS to show the Accessibility and Screen Recording prompts.
    func requestTrust()
    /// Keyboard/text events go to `pid` only; pointer events (pid nil) are posted
    /// globally after the hit-test.
    func post(_ event: SyntheticEvent, toPid pid: Int?)
}
