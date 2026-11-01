// sol-drive.md §2 check 6 / §2.2: chords parse strictly; the allowlist and the denied
// chords are order-insensitive.
import XCTest
@testable import SolusInputCore

final class ChordTests: XCTestCase {
    func testParsesModifiersAndAKeyCaseInsensitivelyWithAliases() throws {
        let chord = try XCTUnwrap(Chord.parse("Command+Alt+Control+shift+A"))
        XCTAssertEqual(chord.modifiers, [.command, .option, .control, .shift])
        XCTAssertEqual(chord.key, "a")
        XCTAssertEqual(Chord.parse("escape")?.modifiers, [])
    }

    func testRejectsUnknownKeysTwoKeysOrModifiersAlone() {
        for bad in ["", "cmd+banana", "a+b", "cmd+shift", "cmd++a", "cmd+cmd+a"] {
            XCTAssertNil(Chord.parse(bad), bad)
        }
    }

    func testOnlyAllowlistedChordsPassInAnyModifierOrder() {
        for denied in ["cmd+q", "cmd+w", "cmd+tab", "cmd+space", "ctrl+cmd+q", "cmd+option+escape",
                       "shift+cmd+3", "cmd+shift+5", "ctrl+right", "cmd+h", "cmd+m", "cmd+s",
                       "shift+cmd+s", "cmd+p", "cmd+`", "f3", "f11", "shift+f1", "ctrl+f2", "ctrl+a",
                       "option+e", "cmd+option+z", "cmd+k", "cmd+shift+c", "ctrl+space",
                       // ADR-041 §5: no clipboard access — copy/cut overwrite the user's
                       // clipboard, paste could leak a copied secret into a capture.
                       "cmd+c", "cmd+v", "cmd+x"] {
            XCTAssertFalse(ChordPolicy.allows(Chord.parse(denied)!), denied)
        }
        for allowed in ["cmd+z", "shift+cmd+z", "escape", "a", "shift+a", "return", "delete", "e",
                        "w", "cmd+a", "cmd+f", "cmd+=", "cmd+-", "up",
                        "shift+left", "tab", "space", "5"] {
            XCTAssertTrue(ChordPolicy.allows(Chord.parse(allowed)!), allowed)
        }
    }

    func testProjectBoundAppsAreExactlyKiCadsSchematicHosts() {
        XCTAssertEqual(ProjectBoundApps.bundleIds, ["org.kicad.kicad", "org.kicad.eeschema"])
    }

    // sol-drive.md §2.2: save/close/quit/print are pinned by `DeniedChords`, including
    // the option and shift variants, independent of the allowlist.
    func testDeniedChordsIncludeOptionAndShiftVariantsAndNeverPassTheAllowlist() {
        for text in ["cmd+s", "shift+cmd+s", "option+cmd+s", "cmd+option+shift+s", "cmd+w", "cmd+shift+w",
                     "alt+cmd+w", "cmd+q", "cmd+shift+q", "cmd+opt+q", "cmd+alt+shift+q", "cmd+p", "cmd+shift+p",
                     "cmd+option+p"] {
            let chord = Chord.parse(text)!
            XCTAssertTrue(DeniedChords.denies(chord), text)
            XCTAssertFalse(ChordPolicy.allows(chord), text)
        }
        for text in ["cmd+option+shift+w", "cmd+option+shift+p", "ctrl+cmd+q", "s", "w", "q", "p", "shift+p"] {
            XCTAssertFalse(DeniedChords.denies(Chord.parse(text)!), text)
        }
    }
}
