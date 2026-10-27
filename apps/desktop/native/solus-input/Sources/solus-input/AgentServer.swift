// `solus-input serve` — the launchd agent's socket loop (sol-drive.md §2.1).
// Thin I/O only: every decision about a request is SolusInputCore.Agent's.
// Peer identity is the audit token the kernel captured at connect
// (LOCAL_PEERTOKEN), so a process that connects and then execs a signed binary
// is still judged as what it was when it connected.
import Foundation
import Security
import SolusInputCore

/// <sys/un.h>: SOL_LOCAL / LOCAL_PEERTOKEN (not all are imported into Swift).
private let solLocal: Int32 = 0
private let localPeerToken: Int32 = 0x006
/// How long a connected peer has to send its request line.
private let requestDeadlineSeconds = 5
private let listenBacklog: Int32 = 16

struct ServeFailure: Error { let message: String }

struct AgentServer {
    let agent: Agent
    let socketPath: String

    /// Prepares the private directory and the socket, or throws (the agent then exits).
    static func make(agent: Agent, directory: String, noSymlinksBelow root: String?) throws -> (AgentServer, Int32) {
        try ensurePrivateDirectory(directory, noSymlinksBelow: root)
        let path = directory + "/" + ServeOptions.socketName
        guard path.utf8.count < MemoryLayout.size(ofValue: sockaddr_un().sun_path) else {
            throw ServeFailure(message: "the socket path is longer than a Unix socket allows (104 bytes)")
        }
        try clearStaleSocket(path)
        return (AgentServer(agent: agent, socketPath: path), try listen(at: path))
    }

    func serve(_ listener: Int32) -> Never {
        while true {
            let fd = accept(listener, nil, nil)
            if fd < 0 { continue }
            handle(fd)
            close(fd)
            if StopFlag.shared.signalled { exit(0) }
        }
    }

    // MARK: one connection

    private func handle(_ fd: Int32) {
        var on: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        var deadline = timeval(tv_sec: requestDeadlineSeconds, tv_usec: 0)
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &deadline, socklen_t(MemoryLayout<timeval>.size))
        let line = readLine(fd)
        let peer = PeerIdentity(fd: fd)
        guard StopFlag.shared.begin(fd) else { exit(0) }
        let reply = agent.handle(line, peerSatisfies: peer.satisfies)
        StopFlag.shared.end()
        writeAll(fd, Data((reply + "\n").utf8))
    }

    /// Up to the first newline, at most one byte past the limit (the agent refuses it).
    private func readLine(_ fd: Int32) -> Data {
        var data = Data()
        var chunk = [UInt8](repeating: 0, count: 4_096)
        while data.count <= Agent.maxLineBytes, !data.contains(0x0A) {
            let want = min(chunk.count, Agent.maxLineBytes + 2 - data.count)
            let got = recv(fd, &chunk, want, 0)
            if got <= 0 { break }
            data.append(contentsOf: chunk[0..<got])
        }
        return data // anything after the line makes it malformed; the agent refuses it
    }

    private func writeAll(_ fd: Int32, _ data: Data) {
        data.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                let sent = send(fd, raw.baseAddress! + offset, raw.count - offset, 0)
                if sent <= 0 { return }
                offset += sent
            }
        }
    }

    // MARK: socket setup

    /// The directory is created 0700; one that exists must be a real directory
    /// (no symlink) owned by this user with no group/other bits. Components
    /// below `root` (the home directory) must not be symlinks either.
    static func ensurePrivateDirectory(_ path: String, noSymlinksBelow root: String?) throws {
        var prefix = ""
        for part in path.split(separator: "/") {
            prefix += "/" + part
            var info = stat()
            if lstat(prefix, &info) != 0 {
                guard errno == ENOENT, mkdir(prefix, 0o700) == 0 else {
                    throw ServeFailure(message: "cannot create the socket directory")
                }
                continue
            }
            if let root, prefix.utf8.count > root.utf8.count, prefix.hasPrefix(root + "/"),
               info.st_mode & S_IFMT == S_IFLNK {
                throw ServeFailure(message: "a symlink is on the socket directory's path")
            }
        }
        var info = stat()
        guard lstat(path, &info) == 0, info.st_mode & S_IFMT == S_IFDIR else {
            throw ServeFailure(message: "the socket directory is not a directory")
        }
        guard info.st_uid == getuid(), info.st_mode & 0o077 == 0 else {
            throw ServeFailure(message: "the socket directory must be 0700 and owned by this user")
        }
    }

    /// Unlinked only when it is a socket nothing accepts on; a live one means
    /// another agent is serving, and anything else is refused.
    static func clearStaleSocket(_ path: String) throws {
        var info = stat()
        guard lstat(path, &info) == 0 else { return }
        guard info.st_mode & S_IFMT == S_IFSOCK else { throw ServeFailure(message: "the socket path is not a socket") }
        let probe = socket(AF_UNIX, SOCK_STREAM, 0)
        defer { close(probe) }
        let connected = withAddress(path) { connect(probe, $0, $1) } == 0
        guard !connected else { throw ServeFailure(message: "another agent is serving on this socket") }
        guard unlink(path) == 0 else { throw ServeFailure(message: "cannot remove the stale socket") }
    }

    static func listen(at path: String) throws -> Int32 {
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw ServeFailure(message: "cannot create the socket") }
        let previous = umask(0o177) // the socket file is born 0600
        let bound = withAddress(path) { bind(fd, $0, $1) }
        umask(previous)
        guard bound == 0, chmod(path, 0o600) == 0, Darwin.listen(fd, listenBacklog) == 0 else {
            close(fd)
            throw ServeFailure(message: "cannot listen on the socket")
        }
        return fd
    }

    private static func withAddress(_ path: String, _ body: (UnsafePointer<sockaddr>, socklen_t) -> Int32) -> Int32 {
        var address = sockaddr_un()
        let bytes = Array(path.utf8)
        guard bytes.count < MemoryLayout.size(ofValue: address.sun_path) else { return -1 }
        address.sun_family = sa_family_t(AF_UNIX)
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        withUnsafeMutableBytes(of: &address.sun_path) { raw in
            raw.copyBytes(from: bytes)
            raw[bytes.count] = 0
        }
        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { body($0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
        }
    }
}

/// The peer's code, from its connect-time audit token; looked up once per connection.
private final class PeerIdentity {
    private let code: SecCode?

    init(fd: Int32) {
        var token = audit_token_t()
        var size = socklen_t(MemoryLayout<audit_token_t>.size)
        guard getsockopt(fd, solLocal, localPeerToken, &token, &size) == 0,
              size == socklen_t(MemoryLayout<audit_token_t>.size) else { code = nil; return }
        let tokenData = withUnsafeBytes(of: &token) { Data($0) }
        var guest: SecCode?
        let attributes = [kSecGuestAttributeAudit: tokenData] as CFDictionary
        code = SecCodeCopyGuestWithAttributes(nil, attributes, [], &guest) == errSecSuccess ? guest : nil
    }

    func satisfies(_ requirement: String) -> Bool {
        var parsed: SecRequirement?
        guard let code, SecRequirementCreateWithString(requirement as CFString, [], &parsed) == errSecSuccess,
              let parsed else { return false }
        return SecCodeCheckValidity(code, [], parsed) == errSecSuccess
    }
}

/// 32 bytes from the system CSPRNG; nil on failure (no token is issued).
func secureRandom(_ count: Int) -> [UInt8]? {
    var bytes = [UInt8](repeating: 0, count: count)
    return SecRandomCopyBytes(kSecRandomDefault, count, &bytes) == errSecSuccess ? bytes : nil
}
