// swift-tools-version:5.9
// solus-input — the ADR-041 input/capture helper (docs/architecture/sol-drive.md §2).
// SolusInputCore is pure (parsing, checks, event planning) and fully unit-tested;
// the executable is a thin macOS layer behind `SystemPort`.
import PackageDescription

let package = Package(
    name: "solus-input",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "SolusInputCore"),
        .executableTarget(name: "solus-input", dependencies: ["SolusInputCore"]),
        .testTarget(name: "SolusInputCoreTests", dependencies: ["SolusInputCore"]),
    ]
)
