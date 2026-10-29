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
    /// Solus.app builds below this CFBundleVersion are never admitted (a human bumps it).
    public static let appVersionFloor = SOLUS_APP_VERSION_FLOOR

    /// Developer ID: Apple anchor, the Developer ID intermediate (…6.2.6) and
    /// Developer ID Application leaf (…6.1.13), pinned to the team and identifier.
    public static func requirement(teamId: String, identifier: String) -> String {
        fill(SOLUS_REQUIREMENT_FORMAT, [teamId, identifier])
    }

    /// What every connection to the Mach service must satisfy: Solus.app, with no
    /// entitlement admitting foreign code or a debugger, at or above the version
    /// floor. Nil (admit nobody) until the team ID is real.
    public static func listenerRequirement(teamId: String) -> String? {
        guard isRealTeamId(teamId) else { return nil }
        return requirement(teamId: teamId, identifier: appIdentifier) + fill(SOLUS_APP_REQUIREMENT_SUFFIX, [appVersionFloor])
    }

    /// The C formats' `%s` placeholders, filled in order without printf (`%s`
    /// wants C strings, and nothing else in them is a directive).
    private static func fill(_ format: String, _ values: [String]) -> String {
        let parts = format.components(separatedBy: "%s")
        precondition(parts.count == values.count + 1, "format placeholder count")
        return zip(parts, values + [""]).map { $0 + $1 }.joined()
    }

    /// Apple team IDs are ten upper-case letters or digits (nothing that could
    /// change the requirement's meaning).
    static func isRealTeamId(_ teamId: String) -> Bool {
        teamId != teamIdPlaceholder && teamId.utf8.count == 10
            && teamId.utf8.allSatisfy { (0x30...0x39).contains($0) || (0x41...0x5A).contains($0) }
    }
}
