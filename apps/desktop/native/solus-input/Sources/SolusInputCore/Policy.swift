// The Solus-authored policy compiled into the helper (ADR-041 §3, §5;
// sol-drive.md §2). Widening any of it is an ADR-041 amendment.

/// Apps SOL may drive, by bundle identifier. KiCad's schematic editor runs
/// inside the project manager (`org.kicad.kicad`) or standalone (`eeschema`).
public enum DrivableApps {
    public static let bundleIds = ["org.kicad.kicad", "org.kicad.eeschema"]
    public static func allows(_ bundleId: String) -> Bool { bundleIds.contains(bundleId) }
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
public enum ChordPolicy {
    static let functionKeys: Set<String> = Set((1...12).map { "f\($0)" })
    static let commandKeys: Set<String> = ["z", "c", "v", "x", "a", "f", "g", "=", "-", "0"]

    public static func allows(_ chord: Chord) -> Bool {
        switch chord.modifiers {
        case [], [.shift]: return KeyMap.canonical(chord.key) != nil && !functionKeys.contains(chord.key)
        case [.command]: return commandKeys.contains(chord.key)
        case [.command, .shift]: return chord.key == "z"
        default: return false
        }
    }
}
