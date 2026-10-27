// Code requirements the agent checks (ADR-041 amendments C1 and 3b; sol-drive.md
// §2.1): its socket peers (Solus.app, the companion) and its own code at start.

public enum Signing {
    /// Replaced by a human with Solus's Apple team ID. While it is the
    /// placeholder, every peer check fails, so a release agent serves nothing (fails closed).
    public static let teamIdPlaceholder = "SOLUS_TEAM_ID_PLACEHOLDER"
    public static let teamId = teamIdPlaceholder
    public static let companionIdentifier = "com.solusforge.solus.companion"
    public static let appIdentifier = "com.solusforge.solus"
    public static let helperIdentifier = "com.solusforge.solus.input"

    /// Developer ID: Apple anchor, the Developer ID intermediate (…6.2.6) and
    /// Developer ID Application leaf (…6.1.13), pinned to the team and identifier.
    public static func requirement(teamId: String, identifier: String) -> String {
        "anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6]"
            + " and certificate leaf[field.1.2.840.113635.100.6.1.13]"
            + #" and certificate leaf[subject.OU] = "\#(teamId)" and identifier "\#(identifier)""#
    }

    /// Apple team IDs are ten upper-case letters or digits (nothing that could
    /// change the requirement's meaning).
    static func isRealTeamId(_ teamId: String) -> Bool {
        teamId != teamIdPlaceholder && teamId.utf8.count == 10
            && teamId.utf8.allSatisfy { (0x30...0x39).contains($0) || (0x41...0x5A).contains($0) }
    }
}
