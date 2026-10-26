// sol-drive.md §2 check 5: chords parse strictly and the denylist is order-insensitive.
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

    func testDenylistBlocksSystemAndOutsideEffectChordsInAnyOrder() {
        for denied in ["cmd+q", "cmd+w", "cmd+tab", "cmd+space", "ctrl+cmd+q", "cmd+option+escape",
                       "shift+cmd+3", "cmd+shift+5", "ctrl+right", "cmd+h", "cmd+m", "cmd+s",
                       "shift+cmd+s", "cmd+p", "cmd+`"] {
            XCTAssertTrue(Denylist.denies(Chord.parse(denied)!), denied)
        }
        for allowed in ["cmd+z", "shift+cmd+z", "escape", "a", "return", "delete", "e", "w", "cmd+c", "up"] {
            XCTAssertFalse(Denylist.denies(Chord.parse(allowed)!), allowed)
        }
    }

    func testDrivableAppsAreExactlyKiCadsSchematicHostsForNow() {
        XCTAssertEqual(DrivableApps.bundleIds, ["org.kicad.kicad", "org.kicad.eeschema"])
    }
}
