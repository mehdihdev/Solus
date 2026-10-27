// solus-input — ADR-041 / docs/architecture/sol-drive.md §2, §2.1.
// Release: runs only as the launchd agent (`serve`); any other invocation is a
// `usage` reply. Debug (`SOLUS_INPUT_UNSIGNED_DEV`, Package.swift debug only)
// also runs the commands from argv for tests — one JSON line out, exit 0.
import Foundation
import SolusInputCore

#if SOLUS_INPUT_UNSIGNED_DEV
let unsignedDev = true
#else
let unsignedDev = false
#endif

let argv = Array(CommandLine.arguments.dropFirst())
let port = MacSystem()
let serving = argv.first == "serve"

// SIGTERM stops a run between events (a held button is released). While
// serving, launchd stopping the agent exits at once when idle, else after the run.
signal(SIGTERM, SIG_IGN)
let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
terminate.setEventHandler {
    if serving { if StopFlag.shared.raiseIsIdle() { exit(0) } } else { StopFlag.shared.raise() }
}
terminate.resume()

func fatal(_ message: String) -> Never {
    fputs("solus-input: \(message)\n", stderr)
    exit(1)
}

if serving {
    // A peer that hangs up before its reply must not kill the agent (and its token):
    // SO_NOSIGPIPE alone does not hold on a connection already closed at accept.
    signal(SIGPIPE, SIG_IGN)
    guard let options = ServeOptions.parse(argv, unsignedDev: unsignedDev) else {
        print(#"{"code":"usage","message":"serve\#(unsignedDev ? " [--socket-dir DIR]" : "")","ok":false}"#)
        exit(0)
    }
    guard Agent.startAllowed(teamId: Signing.teamId, unsignedDev: unsignedDev, port: port) else {
        fatal("this agent's own signature does not satisfy its requirement")
    }
    guard let home = port.homeDirectory() else { fatal("cannot read the home directory") }
    let agent = Agent(runner: Runner(port: port, unsignedDev: unsignedDev), teamId: Signing.teamId,
                      unsignedDev: unsignedDev, random: secureRandom)
    do {
        let (server, listener) = try AgentServer.make(
            agent: agent, directory: options.socketDir ?? ServeOptions.defaultDirectory(home: home),
            noSymlinksBelow: options.socketDir == nil ? home : nil)
        server.serve(listener)
    } catch let failure as ServeFailure {
        fatal(failure.message)
    } catch {
        fatal("cannot serve")
    }
}

print(unsignedDev ? Runner(port: port, unsignedDev: true).run(argv) : Runner.agentOnlyUsage)
exit(0)
