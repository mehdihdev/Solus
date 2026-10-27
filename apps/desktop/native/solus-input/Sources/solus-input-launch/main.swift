// solus-input-launch — sol-drive.md §5 "The launcher". Replaces itself (same pid,
// so the helper's parent is still the companion) with the sibling `solus-input`,
// with responsibility disclaimed so macOS attributes the helper's Accessibility
// and Screen Recording use to the helper bundle, not to its ancestors. Runs
// nothing else, with a fixed minimal environment. On any failure it exits
// non-zero with nothing on stdout — it never runs the helper undisclaimed.
import Darwin
import MachO
import SolusInputCore

/// Private SPI in libsystem: `int responsibility_spawnattrs_setdisclaim(posix_spawnattr_t *, int)`.
typealias SetDisclaim = @convention(c) (UnsafeMutablePointer<posix_spawnattr_t?>, Int32) -> Int32

func fail(_ reason: String) -> Never {
    fputs("solus-input-launch: \(reason)\n", stderr)
    exit(70) // EX_SOFTWARE; the companion reports helper_crashed
}

func ownPath() -> String? {
    var size: UInt32 = 0
    _ = _NSGetExecutablePath(nil, &size)
    var raw = [CChar](repeating: 0, count: Int(size) + 1)
    guard _NSGetExecutablePath(&raw, &size) == 0, let resolved = realpath(raw, nil) else { return nil }
    defer { free(resolved) }
    return String(cString: resolved)
}

guard let launcher = ownPath(), let helper = Launcher.sibling(of: launcher) else { fail("cannot resolve own path") }
guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_spawnattrs_setdisclaim") else {
    fail("responsibility disclaim unavailable") // RTLD_DEFAULT is (void *)-2 on Darwin
}
let setDisclaim = unsafeBitCast(symbol, to: SetDisclaim.self)

var attributes: posix_spawnattr_t?
guard posix_spawnattr_init(&attributes) == 0 else { fail("spawn attributes unavailable") }
guard posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETEXEC)) == 0,
      setDisclaim(&attributes, 1) == 0
else { fail("cannot disclaim responsibility") }

let argv: [UnsafeMutablePointer<CChar>?] = ([helper] + CommandLine.arguments.dropFirst()).map { strdup($0) } + [nil]
var pid: pid_t = 0
// With POSIX_SPAWN_SETEXEC this only returns on failure.
let envp: [UnsafeMutablePointer<CChar>?] = Launcher.environment.map { strdup($0) } + [nil]
let status = posix_spawn(&pid, helper, nil, &attributes, argv, envp)
fail("exec failed (\(status))")
