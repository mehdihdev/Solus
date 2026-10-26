// argv → a command, strictly: `--name value` pairs plus at most one bare verb.
// Anything unexpected is a usage error, never a guess.

struct Arguments {
    let command: String
    let verb: String?
    private let options: [String: String]

    /// `argv` WITHOUT the program name.
    init?(_ argv: [String]) {
        guard let first = argv.first, !first.hasPrefix("--") else { return nil }
        var options: [String: String] = [:]
        var verb: String?
        var index = 1
        while index < argv.count {
            let token = argv[index]
            if token.hasPrefix("--") {
                let name = String(token.dropFirst(2))
                guard !name.isEmpty, index + 1 < argv.count, options[name] == nil else { return nil }
                options[name] = argv[index + 1]
                index += 2
            } else {
                guard verb == nil else { return nil }
                verb = token
                index += 1
            }
        }
        command = first
        self.verb = verb
        self.options = options
    }

    func has(only allowed: Set<String>) -> Bool { Set(options.keys).isSubset(of: allowed) }
    func string(_ name: String) -> String? { options[name] }
    func int(_ name: String) -> Int? { options[name].flatMap { Int($0) } }
    func double(_ name: String) -> Double? { options[name].flatMap { Double($0) } }
    func windowId(_ name: String) -> UInt32? { options[name].flatMap { UInt32($0) } }
}
