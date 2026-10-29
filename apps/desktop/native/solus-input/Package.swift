// swift-tools-version:5.9
// solus-input — the ADR-041 input/capture helper (docs/architecture/sol-drive.md §2, §2.1).
// SolusInputShared is the XPC interface + signing constants (one ObjC header, also
// compiled into the desktop's native module); SolusInputCore is pure (parsing,
// checks, event planning) and fully unit-tested; SolusInputXPC is the listener
// glue; the executable is a thin macOS layer behind `SystemPort`, run by launchd
// as the XPC agent (`serve`).
import PackageDescription

let package = Package(
    name: "solus-input",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "SolusInputShared"),
        .target(name: "SolusInputCore", dependencies: ["SolusInputShared"]),
        .target(name: "SolusInputXPC", dependencies: ["SolusInputCore", "SolusInputShared"]),
        // Debug builds only: no XPC listener, the commands run from argv (one process
        // per call), every code-requirement check is skipped. Release runs only as `serve`.
        .executableTarget(
            name: "solus-input", dependencies: ["SolusInputCore", "SolusInputXPC"],
            swiftSettings: [.define("SOLUS_INPUT_UNSIGNED_DEV", .when(configuration: .debug))]),
        .testTarget(name: "SolusInputCoreTests", dependencies: ["SolusInputCore"]),
        .testTarget(name: "SolusInputXPCTests", dependencies: ["SolusInputXPC", "SolusInputCore", "SolusInputShared"]),
    ]
)
