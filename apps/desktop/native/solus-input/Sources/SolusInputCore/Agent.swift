// The agent's request handling (sol-drive.md §2.1; ADR-041 amendments C1 and 3b).
// Pure: the socket I/O, the peer's audit-token identity and the random source
// are injected by the executable. A request reaches the runner only when the
// peer's code satisfies the op's requirement AND (for `run`) it carries the
// current session token, which only Solus.app can obtain.
import Foundation

public final class Agent {
    public static let maxLineBytes = 65_536
    static let tokenBytes = 32
    static let runnable: Set<String> = ["identify", "capture", "act"]
    static let maxArgv = 64

    private let runner: Runner
    private let teamId: String
    private let unsignedDev: Bool
    private let random: (Int) -> [UInt8]?
    /// Only in memory: a restart invalidates it.
    private var token: [UInt8]?

    public init(runner: Runner, teamId: String, unsignedDev: Bool, random: @escaping (Int) -> [UInt8]?) {
        self.runner = runner; self.teamId = teamId; self.unsignedDev = unsignedDev; self.random = random
    }

    /// Release: the helper's own code must satisfy its pinned requirement, or the agent exits.
    public static func startAllowed(teamId: String, unsignedDev: Bool, port: SystemPort) -> Bool {
        unsignedDev || (Signing.isRealTeamId(teamId)
            && port.ownCodeSatisfies(requirement: Signing.requirement(teamId: teamId, identifier: Signing.helperIdentifier)))
    }

    /// `raw` is everything read from the connection: one `\n`-terminated line.
    public func handle(_ raw: Data, peerSatisfies: (String) -> Bool) -> String {
        guard let request = Request.parse(raw) else { return Self.refusal("usage", "malformed request") }
        guard admits(request.peer, peerSatisfies) else {
            return Self.refusal("caller_untrusted", "this request is not from Solus")
        }
        switch request {
        case .session: return session()
        case .trust(let prompt): return runner.run(prompt ? ["trust", "--prompt"] : ["trust"])
        case .run(let presented, let argv):
            guard let presented, let token, Self.constantTimeEqual(Array(presented.utf8), token) else {
                return Self.refusal("bad_token", "missing, wrong or superseded session token")
            }
            return runner.run(argv)
        }
    }

    private func admits(_ identifier: String, _ peerSatisfies: (String) -> Bool) -> Bool {
        unsignedDev || (Signing.isRealTeamId(teamId)
            && peerSatisfies(Signing.requirement(teamId: teamId, identifier: identifier)))
    }

    /// A new session revokes the old token first, so a failed draw leaves none.
    private func session() -> String {
        token = nil
        guard let bytes = random(Self.tokenBytes), bytes.count == Self.tokenBytes else {
            return Self.refusal("usage", "could not issue a session token")
        }
        let encoded = Self.base64url(bytes)
        token = Array(encoded.utf8)
        return Self.encode(["ok": true, "token": encoded])
    }

    static func base64url(_ bytes: [UInt8]) -> String {
        Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    /// No early exit on content (the token's length is public: 43).
    static func constantTimeEqual(_ a: [UInt8], _ b: [UInt8]) -> Bool {
        guard a.count == b.count else { return false }
        return zip(a, b).reduce(UInt8(0)) { $0 | ($1.0 ^ $1.1) } == 0
    }

    static func refusal(_ code: String, _ message: String) -> String {
        encode(["ok": false, "code": code, "message": message])
    }

    static func encode(_ object: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else {
            return #"{"code":"usage","message":"unencodable","ok":false}"#
        }
        return String(decoding: data, as: UTF8.self)
    }
}

/// Wire protocol v1: exactly these three shapes, no other fields.
enum Request {
    case session
    case trust(prompt: Bool)
    case run(token: String?, argv: [String])

    /// The code identity the socket peer must have.
    var peer: String {
        switch self {
        case .session, .trust: return Signing.appIdentifier
        case .run: return Signing.companionIdentifier
        }
    }

    static func parse(_ raw: Data) -> Request? {
        guard raw.last == 0x0A, raw.count - 1 <= Agent.maxLineBytes else { return nil }
        let line = raw.dropLast()
        guard !line.contains(0x0A), String(data: line, encoding: .utf8) != nil,
              let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
              isInteger(object["v"], 1), let op = object["op"] as? String
        else { return nil }
        let keys = Set(object.keys)
        switch op {
        case "session" where keys == ["v", "op"]:
            return .session
        case "trust" where keys == ["v", "op", "prompt"]:
            guard let prompt = boolean(object["prompt"]) else { return nil }
            return .trust(prompt: prompt)
        case "run" where keys == ["v", "op", "argv"] || keys == ["v", "op", "argv", "token"]:
            guard let argv = object["argv"] as? [Any], argv.count <= Agent.maxArgv,
                  let strings = argv as? [String], strings.count == argv.count,
                  let command = strings.first, Agent.runnable.contains(command)
            else { return nil }
            if keys.contains("token") {
                guard let token = object["token"] as? String else { return nil }
                return .run(token: token, argv: strings)
            }
            return .run(token: nil, argv: strings)
        default:
            return nil
        }
    }

    private static func isBoolean(_ value: Any?) -> Bool {
        guard let number = value as? NSNumber else { return false }
        return CFGetTypeID(number) == CFBooleanGetTypeID()
    }

    private static func boolean(_ value: Any?) -> Bool? {
        isBoolean(value) ? (value as? NSNumber)?.boolValue : nil
    }

    /// An integer, not a boolean, string or fraction.
    private static func isInteger(_ value: Any?, _ expected: Int) -> Bool {
        guard let number = value as? NSNumber, !isBoolean(number), !(value is String),
              !["d", "f"].contains(String(cString: number.objCType)) else { return false }
        return number.intValue == expected && number.doubleValue == Double(expected)
    }
}

/// `serve` options. Release: bare `serve` only. Debug: `--socket-dir DIR` too.
public struct ServeOptions: Equatable {
    public static let socketName = "agent.sock"
    public let socketDir: String?

    public init(socketDir: String?) { self.socketDir = socketDir }

    public static func parse(_ argv: [String], unsignedDev: Bool) -> ServeOptions? {
        if argv == ["serve"] { return ServeOptions(socketDir: nil) }
        guard unsignedDev, argv.count == 3, argv[0] == "serve", argv[1] == "--socket-dir",
              argv[2].hasPrefix("/"), argv[2] != "/" else { return nil }
        return ServeOptions(socketDir: argv[2])
    }

    public static func defaultDirectory(home: String) -> String {
        home + "/Library/Application Support/Solus/drive"
    }
}

/// Cancellation (§2.1): during a `run` the agent polls the connection between events.
public enum PeerWatch {
    /// Hang-up, an error, or a readable socket with nothing to read (EOF). Extra
    /// bytes after the request line do not count; a peer must not half-close.
    public static func hasClosed(_ fd: Int32) -> Bool {
        guard fd >= 0 else { return true } // poll ignores negative descriptors
        var probe = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
        let ready = poll(&probe, 1, 0)
        if ready < 0 { return true }
        guard ready > 0 else { return false }
        if probe.revents & Int16(POLLHUP | POLLERR | POLLNVAL) != 0 { return true }
        var byte: UInt8 = 0
        return recv(fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT) == 0
    }
}
