// The agent's request handling (sol-drive.md §2.1; ADR-041 amendment 2026-10-28).
// Who may send is enforced by XPC code requirements on both ends, before a
// message reaches `handle`; this only parses the request strictly and hands it
// to the runner. Pure and unit-tested.
import Foundation
import SolusInputShared

public final class Agent {
    public static let maxRequestBytes = Int(SOLUS_AGENT_MAX_REQUEST_BYTES)
    static let runnable: Set<String> = ["identify", "capture", "act"]
    static let maxArgv = 64

    private let runner: Runner

    public init(runner: Runner) { self.runner = runner }

    /// Release: the helper's own code must satisfy its pinned requirement, or the agent exits.
    public static func startAllowed(teamId: String, unsignedDev: Bool, port: SystemPort) -> Bool {
        unsignedDev || (Signing.isRealTeamId(teamId)
            && port.ownCodeSatisfies(requirement: Signing.requirement(teamId: teamId, identifier: Signing.helperIdentifier)))
    }

    /// One JSON object in, one JSON object out.
    public func handle(_ request: Data) -> Data {
        let line: String
        switch Request.parse(request) {
        case .trust(let prompt): line = runner.run(prompt ? ["trust", "--prompt"] : ["trust"])
        case .run(let argv): line = runner.run(argv)
        case nil: line = #"{"code":"usage","message":"malformed request","ok":false}"#
        }
        return Data(line.utf8)
    }
}

/// Wire protocol v1: exactly these two shapes, no other fields.
enum Request {
    case trust(prompt: Bool)
    case run(argv: [String])

    static func parse(_ raw: Data) -> Request? {
        guard raw.count <= Agent.maxRequestBytes, String(data: raw, encoding: .utf8) != nil,
              let object = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
              isInteger(object["v"], 1), let op = object["op"] as? String
        else { return nil }
        let keys = Set(object.keys)
        switch op {
        case "trust" where keys == ["v", "op", "prompt"]:
            return isBoolean(object["prompt"]) ? .trust(prompt: (object["prompt"] as! NSNumber).boolValue) : nil
        case "run" where keys == ["v", "op", "argv"]:
            guard let argv = object["argv"] as? [Any], argv.count <= Agent.maxArgv,
                  let strings = argv as? [String], strings.count == argv.count,
                  let command = strings.first, Agent.runnable.contains(command)
            else { return nil }
            return .run(argv: strings)
        default:
            return nil
        }
    }

    private static func isBoolean(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID()
    }

    /// An integer, not a boolean, string or fraction.
    private static func isInteger(_ value: Any?, _ expected: Int) -> Bool {
        guard let number = value as? NSNumber, !isBoolean(number),
              !["d", "f"].contains(String(cString: number.objCType)) else { return false }
        return number.intValue == expected
    }
}

/// The agent exits once nothing has run or been queued for 60 s; launchd starts
/// it again on the next message (§2.1, no KeepAlive).
public enum IdlePolicy {
    public static let timeoutSeconds = 60.0

    public static func shouldExit(now: Double, lastActivity: Double, pending: Int) -> Bool {
        pending == 0 && now - lastActivity >= timeoutSeconds
    }
}

/// Why a run stops between events: `cancel()` or the invalidation of the
/// connection that sent it, or SIGTERM. The runner reads `isRaised` (through
/// `SystemPort.stopRequested`) before every event.
public final class StopSignal: @unchecked Sendable {
    public static let shared = StopSignal()
    private let lock = NSLock()
    private var terminating = false
    private var cancelled = false
    private var owner: AnyObject?

    public init() {}

    public var isRaised: Bool { lock.lock(); defer { lock.unlock() }; return terminating || cancelled }

    /// A request from `owner` (its connection) starts clear. False once terminating.
    public func begin(_ owner: AnyObject) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !terminating else { return false }
        self.owner = owner
        cancelled = false
        return true
    }

    public func end() { lock.lock(); owner = nil; cancelled = false; lock.unlock() }

    /// Stops `owner`'s running request; with nothing of its running, does nothing.
    public func cancel(_ owner: AnyObject) {
        lock.lock(); defer { lock.unlock() }
        if self.owner === owner { cancelled = true }
    }

    /// SIGTERM while serving: true when idle (exit now), else the run stops and the agent exits after.
    public func terminate() -> Bool { lock.lock(); defer { lock.unlock() }; terminating = true; return owner == nil }

    /// SIGTERM in debug argv mode (one process, one call).
    public func raise() { lock.lock(); terminating = true; lock.unlock() }
}
