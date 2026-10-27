// swift-tools-version:5.9
// solus-input — the ADR-041 input/capture helper (docs/architecture/sol-drive.md §2).
// SolusInputCore is pure (parsing, checks, event planning) and fully unit-tested;
// the executable is a thin macOS layer behind `SystemPort`, run by launchd as
// the agent (`serve`, §2.1).
import PackageDescription

let package = Package(
    name: "solus-input",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "SolusInputCore"),
        // Debug builds only: skip the agent's code-requirement checks (never the session
        // token) and keep the argv commands for tests. Release runs only as `serve`.
        .executableTarget(
            name: "solus-input", dependencies: ["SolusInputCore"],
            swiftSettings: [.define("SOLUS_INPUT_UNSIGNED_DEV", .when(configuration: .debug))]),
        .testTarget(name: "SolusInputCoreTests", dependencies: ["SolusInputCore"]),
    ]
)
