// Who may run solus-input (ADR-041 amendment 2026-10-27; sol-drive.md §2 "Caller").
// The helper's parent must be the top-level signed companion, and the
// companion's parent Solus.app. Pids come from the kernel and requirements are
// checked by the code-signing service (via `SystemPort`) — never from argv or
// the environment, which the caller controls.

public enum Signing {
    /// Replaced by a human with Solus's Apple team ID. While it is the
    /// placeholder, a release build refuses every call (fails closed).
    public static let teamIdPlaceholder = "SOLUS_TEAM_ID_PLACEHOLDER"
    public static let teamId = teamIdPlaceholder
    public static let companionIdentifier = "com.solusforge.solus.companion"
    public static let appIdentifier = "com.solusforge.solus"

    public static func requirement(teamId: String, identifier: String) -> String {
        #"anchor apple generic and certificate leaf[subject.OU] = "\#(teamId)" and identifier "\#(identifier)""#
    }

    /// Apple team IDs are ten upper-case letters or digits (nothing that could
    /// change the requirement's meaning).
    static func isRealTeamId(_ teamId: String) -> Bool {
        teamId != teamIdPlaceholder && teamId.utf8.count == 10
            && teamId.utf8.allSatisfy { (0x30...0x39).contains($0) || (0x41...0x5A).contains($0) }
    }
}

/// The executable decides this at compile time (`SOLUS_INPUT_UNSIGNED_DEV` is
/// defined for debug builds only); release builds have no skip path.
public struct CallerPolicy {
    let teamId: String
    let unsignedDev: Bool

    public init(teamId: String) { self.teamId = teamId; unsignedDev = false }
    private init(unsignedDev: Bool) { teamId = Signing.teamIdPlaceholder; self.unsignedDev = unsignedDev }

    /// Debug builds only: the check is skipped and replies say `unsignedDev: true`.
    public static let unsignedDevelopment = CallerPolicy(unsignedDev: true)

    /// The launchd pid: a helper whose parent died is re-parented to it.
    static let launchdPid = 1

    /// Every value is read, then the chain is re-read: a parent (or grandparent)
    /// that died mid-check re-parents its child, so a reused pid cannot pass.
    func admits(_ port: SystemPort) -> Bool {
        if unsignedDev { return true }
        guard Signing.isRealTeamId(teamId), port.ownSignatureIsValid() else { return false }
        let parent = port.ownParentPid()
        guard parent > Self.launchdPid, let grandparent = port.parentPid(of: parent),
              grandparent > Self.launchdPid,
              port.satisfies(pid: parent, requirement: Signing.requirement(teamId: teamId, identifier: Signing.companionIdentifier)),
              // The top-level companion takes no arguments; a server or command it runs does.
              port.argumentCount(pid: parent) == 1,
              port.satisfies(pid: grandparent, requirement: Signing.requirement(teamId: teamId, identifier: Signing.appIdentifier))
        else { return false }
        return port.ownParentPid() == parent && port.parentPid(of: parent) == grandparent
    }
}

/// `solus-input-launch` runs only the helper beside it.
public enum Launcher {
    public static let helperName = "solus-input"

    /// `path` must be the launcher's own absolute, resolved path.
    public static func sibling(of path: String) -> String? {
        let parts = path.split(separator: "/", omittingEmptySubsequences: false)
        guard path.hasPrefix("/"), parts.count >= 3, let name = parts.last, !name.isEmpty,
              parts.dropFirst().allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." })
        else { return nil }
        return (parts.dropLast() + [Substring(helperName)]).joined(separator: "/")
    }
}
