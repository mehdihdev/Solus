// solus-input — ADR-041 / docs/architecture/sol-drive.md §2.
// argv in, exactly one JSON line out, exit 0 for every outcome (refusals and
// usage errors included). Never reads stdin, never spawns anything.
import Foundation
import SolusInputCore

// SIGTERM (the companion stopping a step) is turned into a flag the posting
// loop checks between events, so a held mouse button is released, not stranded.
signal(SIGTERM, SIG_IGN)
let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
terminate.setEventHandler { StopFlag.shared.raise() }
terminate.resume()

// The caller check (ADR-041 amendment 2026-10-27) is skipped only in debug
// builds, where Package.swift defines SOLUS_INPUT_UNSIGNED_DEV; release has no skip path.
#if SOLUS_INPUT_UNSIGNED_DEV
let caller = CallerPolicy.unsignedDevelopment
#else
let caller = CallerPolicy(teamId: Signing.teamId)
#endif

print(Runner(port: MacSystem(), caller: caller).run(Array(CommandLine.arguments.dropFirst())))
exit(0)
