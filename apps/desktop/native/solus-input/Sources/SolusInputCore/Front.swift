// `identify`'s `front` (sol-drive.md §2.2; ADR-041 amendments 2026-10-31): what
// is in front, whether SOL may drive it and how it would be bound. A denied app,
// or KiCad without (or outside) the workspace, reports no pid, window or title.
import Foundation

extension Runner {
    static let maxNameScalars = 64
    static let maxTitleScalars = 256

    /// nil when nothing is in front or its owner has no usable bundle id.
    func frontJSON(_ root: String?) -> [String: Any]? {
        guard let front = port.frontmost(), DeniedApps.isUsable(front.app.bundleId) else { return nil }
        let app = front.app
        let name = Self.cleaned(app.name, max: Self.maxNameScalars)
        func notDrivable(_ binding: String?, _ reason: String) -> [String: Any] {
            ["drivable": false, "bundleId": app.bundleId, "name": name, "binding": binding ?? NSNull(), "reason": reason]
        }
        let binding: String
        switch AppPolicy.classify(app.bundleId) {
        case .denied: return notDrivable(nil, "denied")
        case .projectBound:
            guard let root else { return notDrivable("project", "no_workspace") }
            // Another project's window title never leaves the machine (M2).
            guard worksInside(pid: app.pid, root) else { return notDrivable("project", "outside_workspace") }
            binding = "project"
        case .windowBound: binding = "window"
        }
        let window = front.window
        return [
            "drivable": true, "binding": binding, "bundleId": app.bundleId, "name": name, "pid": app.pid,
            "windowId": window.map { Int($0.id) } ?? NSNull(),
            "title": window.flatMap(title) ?? NSNull(),
            "bounds": window.map { Self.boundsJSON($0.bounds) } ?? NSNull(),
            "documentDir": window.flatMap { documentDir($0, root) } ?? NSNull(),
        ]
    }

    /// Cleaned and bounded; nil when empty or Screen Recording is not granted.
    private func title(_ window: WindowInfo) -> String? {
        guard port.screenRecordingAllowed() else { return nil }
        let title = Self.cleaned(window.title, max: Self.maxTitleScalars)
        return title.isEmpty ? nil : title
    }

    /// The `AXDocument`'s folder relative to `root` (`""` for the root itself),
    /// resolved and compared by bytes, whole segments; nil when there is no root,
    /// no document, or it lies outside. Never an absolute path.
    func documentDir(_ window: WindowInfo, _ root: String?) -> String? {
        guard let root, let raw = port.documentPath(window: window), raw.hasPrefix("/"),
              let resolved = port.resolvedPath(raw) else { return nil }
        let bytes = Array(resolved.utf8)
        guard let slash = bytes.lastIndex(of: UInt8(ascii: "/")) else { return nil }
        let folder = Array(bytes[..<slash]), base = Array(root.utf8)
        if folder == base { return "" }
        guard folder.starts(with: base + [UInt8(ascii: "/")]) else { return nil }
        return String(decoding: folder[(base.count + 1)...], as: UTF8.self)
    }

    /// Visible text only (no control or format characters), at most `max` scalars.
    static func cleaned(_ text: String, max: Int) -> String {
        var scalars = String.UnicodeScalarView()
        scalars.append(contentsOf: text.unicodeScalars.lazy.filter(isVisibleText).prefix(max))
        return String(scalars)
    }
}
