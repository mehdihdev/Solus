// Code requirements (ADR-041 amendment 2026-10-28; sol-drive.md §2.1): the XPC
// listener admits only Solus.app, the native module accepts only this agent, and
// the agent checks its own code at start. The values live once, in
// SolusInputShared.h, which the desktop's native module compiles too.
import Foundation
import SolusInputShared

public enum Signing {
    public static let teamIdPlaceholder = SOLUS_TEAM_ID_PLACEHOLDER
    /// Replaced by a human (in SolusInputShared.h). While it is the placeholder
    /// every requirement fails: release fails closed.
    public static let teamId = SOLUS_TEAM_ID
    public static let appIdentifier = SOLUS_APP_IDENTIFIER
    public static let helperIdentifier = SOLUS_HELPER_IDENTIFIER
    public static let agentServiceName = SOLUS_AGENT_SERVICE

    /// Developer ID: Apple anchor, the Developer ID intermediate (…6.2.6) and
    /// Developer ID Application leaf (…6.1.13), pinned to the team and identifier.
    public static func requirement(teamId: String, identifier: String) -> String {
        // The C format's two `%s` (team, then identifier), filled without printf:
        // `%s` wants C strings, and nothing else in it is a directive.
        let parts = SOLUS_REQUIREMENT_FORMAT.components(separatedBy: "%s")
        precondition(parts.count == 3, "SOLUS_REQUIREMENT_FORMAT takes exactly two %s")
        return parts[0] + teamId + parts[1] + identifier + parts[2]
    }

    /// What every connection to the Mach service must satisfy; nil (admit nobody)
    /// until the team ID is real.
    public static func listenerRequirement(teamId: String) -> String? {
        isRealTeamId(teamId) ? requirement(teamId: teamId, identifier: appIdentifier) : nil
    }

    /// Apple team IDs are ten upper-case letters or digits (nothing that could
    /// change the requirement's meaning).
    static func isRealTeamId(_ teamId: String) -> Bool {
        teamId != teamIdPlaceholder && teamId.utf8.count == 10
            && teamId.utf8.allSatisfy { (0x30...0x39).contains($0) || (0x41...0x5A).contains($0) }
    }
}
