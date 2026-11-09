// solus-input — ADR-041 / docs/architecture/sol-drive.md §2, §2.1.
// Release: runs only as the launchd XPC agent (`serve`); any other invocation
// is a `usage` reply. Debug (`SOLUS_INPUT_UNSIGNED_DEV`, Package.swift debug
// only): no listener; the commands run from argv, one process per call — one
// JSON line out, exit 0.
import Foundation
import SolusInputCore
import SolusInputXPC

#if SOLUS_INPUT_UNSIGNED_DEV
let unsignedDev = true
#else
let unsignedDev = false
#endif

let argv = Array(CommandLine.arguments.dropFirst())
let port = MacSystem()
let serving = !unsignedDev && argv == ["serve"]
/// How often the idle exit is considered.
let idleCheckSeconds = 5

// SIGTERM stops a run between events (a held button is released). Serving,
// launchd stopping the agent exits at once when idle, else once the running
// request ends and queued ones are refused (AgentService).
var service: AgentService?
signal(SIGTERM, SIG_IGN)
let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
terminate.setEventHandler {
    guard serving, let service else { return StopSignal.shared.raise() }
    if service.terminate() { exit(0) }
}
terminate.resume()

func fatal(_ message: String) -> Never {
    fputs("solus-input: \(message)\n", stderr)
    exit(1)
}

guard serving else {
    print(unsignedDev ? Runner(port: port, unsignedDev: true).run(argv) : Runner.agentOnlyUsage)
    exit(0)
}

guard Agent.startAllowed(teamId: Signing.teamId, unsignedDev: false, port: port),
      let requirement = Signing.listenerRequirement(teamId: Signing.teamId)
else { fatal("this agent's own signature does not satisfy its requirement") }

let agent = Agent(runner: Runner(port: port, unsignedDev: false))
let agentService = AgentService(stop: StopSignal.shared, admitClient: ClientCode.isHardened,
                                handler: { agent.handle($0) })
service = agentService
let listener = AgentListener.machService(requirement: requirement)
listener.delegate = agentService
listener.resume()

let idle = DispatchSource.makeTimerSource(queue: .global())
idle.schedule(deadline: .now() + .seconds(idleCheckSeconds), repeating: .seconds(idleCheckSeconds))
idle.setEventHandler {
    if agentService.exitIfIdle(now: ProcessInfo.processInfo.systemUptime) { exit(0) }
}
idle.resume()
dispatchMain()
