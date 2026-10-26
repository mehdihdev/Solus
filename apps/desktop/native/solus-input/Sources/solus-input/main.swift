// solus-input — ADR-041 / docs/architecture/sol-drive.md §2.
// argv in, exactly one JSON line out, exit 0 for every decided outcome
// (refusals included). Never reads stdin, never spawns anything.
import Foundation
import SolusInputCore

print(Runner(port: MacSystem()).run(Array(CommandLine.arguments.dropFirst())))
exit(0)
