// swift-tools-version:5.9
// solus-input — the ADR-041 input/capture helper (docs/architecture/sol-drive.md §2).
// SolusInputCore is pure (parsing, checks, event planning) and fully unit-tested;
// the executable is a thin macOS layer behind `SystemPort`; `solus-input-launch`
// execs it with responsibility disclaimed.
import PackageDescription

let package = Package(
    name: "solus-input",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "SolusInputCore"),
        // Debug builds only: skip the caller check (unsigned development). Release has no such path.
        .executableTarget(
            name: "solus-input", dependencies: ["SolusInputCore"],
            swiftSettings: [.define("SOLUS_INPUT_UNSIGNED_DEV", .when(configuration: .debug))]),
        // Execs the sibling helper in place with responsibility disclaimed (sol-drive.md §5).
        .executableTarget(name: "solus-input-launch", dependencies: ["SolusInputCore"]),
        .testTarget(name: "SolusInputCoreTests", dependencies: ["SolusInputCore"]),
    ]
)
