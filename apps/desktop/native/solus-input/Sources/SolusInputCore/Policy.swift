// The Solus-authored policy compiled into the helper (ADR-041 §3, §5 and the
// 2026-10-31 amendments; sol-drive.md §2, §2.2). Widening any of it is an ADR-041 amendment.

/// How the helper treats an app, decided from the window owner's bundle id only
/// (sol-drive.md §2.2; ADR-041 amendments 2026-10-31).
public enum AppClass: Equatable {
    /// Never captured, never driven.
    case denied
    /// M2: the window's process works inside `--within` (KiCad).
    case projectBound
    /// Bound to the summon snapshot `{bundleId, pid, windowId}`.
    case windowBound
}

public enum AppPolicy {
    public static func classify(_ bundleId: String) -> AppClass {
        if DeniedApps.denies(bundleId) { return .denied }
        return ProjectBoundApps.contains(bundleId) ? .projectBound : .windowBound
    }
}

/// Apps SOL never drives. Byte-exact match, or — for a family — the entry itself
/// or the entry followed by `.` and anything. An unusable bundle id is denied.
public enum DeniedApps {
    static let exact: Set<String> = [
        // Terminals, shells and script runners
        "com.apple.Terminal", "com.googlecode.iterm2", "dev.warp.Warp-Stable", "dev.warp.Warp-Preview",
        "com.mitchellh.ghostty", "net.kovidgoyal.kitty", "org.alacritty", "com.github.wez.wezterm", "co.zeit.hyper",
        "com.apple.ScriptEditor2", "com.apple.Automator", "com.apple.shortcuts", "com.latenightsw.ScriptDebugger8",
        // General-purpose hosts that open and run anything
        "com.apple.finder",
        // ADR-041 amendment 2026-11-01 (M-1): remote-desktop/VM consoles, launchers, REPLs, imagers.
        "com.apple.ScreenSharing", "com.microsoft.rdc.macos", "com.utmapp.UTM", "com.vmware.fusion",
        "com.teamviewer.TeamViewer", "com.philandro.anydesk", "com.realvnc.vncviewer", "tv.parsec.www",
        "com.raycast.macos", "org.hammerspoon.Hammerspoon", "org.python.IDLE", "org.thonny.Thonny",
        "io.balena.etcher", "org.raspberrypi.imagingutility",
        // ADR-041 amendment 2026-11-10 (SOLUSDEV-322): simulator GUIs. SOL reaches a simulator
        // only through the owned gazebo.*/isaac.* wrappers and the sim_session ledger, never by
        // driving its window. MuJoCo.app (simulate) and the python.org framework process that
        // hosts the pip `mujoco.viewer` and the Gazebo python bindings. Gazebo's own macOS
        // binaries and Isaac Sim (Linux/Windows only) carry no bundle id, which is denied above.
        "org.mujoco.mujoco", "org.python.python",
        // Password managers, credential and consent prompts
        "com.1password.1password", "com.agilebits.onepassword7", "com.bitwarden.desktop",
        "com.dashlane.dashlanephonefinal", "com.lastpass.LastPass", "org.keepassxc.keepassxc",
        "com.apple.keychainaccess", "com.apple.SecurityAgent", "com.apple.loginwindow",
        "com.apple.coreservices.uiagent", "com.apple.UserNotificationCenter",
        // System Settings and administration
        "com.apple.SystemSettings", "com.apple.ActivityMonitor", "com.apple.DiskUtility", "com.apple.installer",
        // Mail and messaging
        "com.apple.mail", "com.microsoft.Outlook", "com.readdle.smartemail-Mac", "com.readdle.SparkDesktop",
        "org.mozilla.thunderbird", "com.mimestream.Mimestream", "com.apple.MobileSMS", "com.apple.FaceTime",
        "com.tinyspeck.slackmacgap", "com.hnc.Discord", "com.microsoft.teams2", "com.microsoft.teams",
        "net.whatsapp.WhatsApp", "ru.keepcoder.Telegram", "org.telegram.desktop",
        "org.whispersystems.signal-desktop", "us.zoom.xos",
        // Web browsers
        "com.apple.Safari", "com.apple.SafariTechnologyPreview", "org.chromium.Chromium", "org.mozilla.firefox",
        "org.mozilla.firefoxdeveloperedition", "org.mozilla.nightly", "company.thebrowser.Browser",
        "company.thebrowser.dia", "com.operasoftware.OperaGX", "com.kagi.kagimacOS", "app.zen-browser.zen",
    ]
    static let families: [String] = [
        "com.apple.Passwords", "com.apple.systempreferences", "com.apple.settings",
        "com.google.Chrome", "com.microsoft.edgemac", "com.brave.Browser", "com.operasoftware.Opera",
        "com.vivaldi.Vivaldi",
        "com.parallels.desktop", "org.virtualbox.app", "com.p5sys.jump", "com.runningwithcrayons.Alfred",
        "com.stairways.keyboardmaestro",
        // Solus itself (app, Electron helpers, drive agent, companion) and the unpackaged dev shell
        "com.solusforge.solus", "com.github.Electron",
    ]
    static let maxLength = 128

    public static func denies(_ bundleId: String) -> Bool {
        guard isUsable(bundleId) else { return true }
        let id = Array(bundleId.utf8)
        if exact.contains(where: { Array($0.utf8) == id }) { return true }
        return families.contains { entry in
            let family = Array(entry.utf8)
            return id == family || id.starts(with: family + Array(".".utf8))
        }
    }

    /// `^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$`, by bytes.
    public static func isUsable(_ bundleId: String) -> Bool {
        let bytes = Array(bundleId.utf8)
        func alnum(_ b: UInt8) -> Bool { (48...57).contains(b) || (65...90).contains(b) || (97...122).contains(b) }
        guard let first = bytes.first, alnum(first), bytes.count <= maxLength else { return false }
        return bytes.allSatisfy { alnum($0) || $0 == UInt8(ascii: ".") || $0 == UInt8(ascii: "-") }
    }
}

/// Apps that keep the M2 working-folder binding and need a linked workspace.
/// KiCad's schematic editor runs inside the project manager or standalone.
public enum ProjectBoundApps {
    public static let bundleIds = ["org.kicad.kicad", "org.kicad.eeschema"]
    public static func contains(_ bundleId: String) -> Bool { bundleIds.contains { Array($0.utf8) == Array(bundleId.utf8) } }
}

/// ANSI-layout virtual key codes for the named keys a chord may use.
public enum KeyMap {
    static let codes: [String: UInt16] = [
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
        "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
        "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
        "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "return": 36,
        "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45,
        "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50, "delete": 51, "escape": 53,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
        "f9": 101, "f10": 109, "f11": 103, "f12": 111, "forwarddelete": 117, "home": 115,
        "end": 119, "pageup": 116, "pagedown": 121, "left": 123, "right": 124, "down": 125,
        "up": 126,
    ]
    static let aliases = ["enter": "return", "esc": "escape", "backspace": "delete"]

    public static func code(for key: String) -> UInt16? { codes[aliases[key] ?? key] }
    static func canonical(_ key: String) -> String? {
        let name = aliases[key] ?? key
        return codes[name] == nil ? nil : name
    }
}

public struct Chord: Equatable {
    public let modifiers: Set<Modifier>
    public let key: String

    static let modifierNames: [String: Modifier] = [
        "cmd": .command, "command": .command, "shift": .shift, "option": .option,
        "opt": .option, "alt": .option, "ctrl": .control, "control": .control,
    ]

    /// `cmd+shift+a` — modifiers in any order, exactly one named key, no repeats.
    public static func parse(_ text: String) -> Chord? {
        let parts = text.lowercased().split(separator: "+", omittingEmptySubsequences: false).map(String.init)
        var modifiers = Set<Modifier>()
        var key: String?
        for part in parts {
            if let modifier = modifierNames[part] {
                guard modifiers.insert(modifier).inserted else { return nil }
            } else {
                guard key == nil, let name = KeyMap.canonical(part) else { return nil }
                key = name
            }
        }
        guard let key else { return nil }
        return Chord(modifiers: modifiers, key: key)
    }
}

/// Chords are ALLOWED, never denied (an allowlist cannot miss a system shortcut):
/// an editing key alone or with shift, or command with the few editing
/// shortcuts SOL needs. Function keys never pass (Mission Control, Show Desktop).
/// No clipboard shortcuts (ADR-041 §5): copy/cut overwrite the user's clipboard
/// and paste could carry a copied secret into the app and the next capture.
public enum ChordPolicy {
    static let functionKeys: Set<String> = Set((1...12).map { "f\($0)" })
    static let commandKeys: Set<String> = ["z", "a", "f", "g", "=", "-", "0"]

    public static func allows(_ chord: Chord) -> Bool {
        switch chord.modifiers {
        case [], [.shift]: return KeyMap.canonical(chord.key) != nil && !functionKeys.contains(chord.key)
        case [.command]: return commandKeys.contains(chord.key)
        case [.command, .shift]: return chord.key == "z"
        default: return false
        }
    }
}

/// Save, close, quit and print — refused for every binding BEFORE the allowlist,
/// so a future widening of `ChordPolicy` can never admit them (sol-drive.md §2.2).
public enum DeniedChords {
    public static let chords: [Chord] = [
        "cmd+s", "cmd+shift+s", "cmd+option+s", "cmd+option+shift+s",
        "cmd+w", "cmd+shift+w", "cmd+option+w",
        "cmd+q", "cmd+shift+q", "cmd+option+q", "cmd+option+shift+q",
        "cmd+p", "cmd+shift+p", "cmd+option+p",
    ].compactMap(Chord.parse)

    public static func denies(_ chord: Chord) -> Bool { chords.contains(chord) }
}
