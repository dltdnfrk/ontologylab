import Darwin
import Foundation

struct ProcessFingerprint: Codable, Equatable {
    let executablePath: String
    let startSeconds: UInt64
    let startMicroseconds: UInt64
    let uid: UInt32
}

struct StorageHolderDiscovery {
    let inspectedPaths: [String]
    let inspectedAtNs: UInt64
    let holders: [Int32: Set<String>]
}

func processFingerprint(_ pid: Int32) throws -> ProcessFingerprint {
    var info = proc_bsdinfo()
    let expected = Int32(MemoryLayout<proc_bsdinfo>.size)
    guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, expected) == expected else {
        throw SupervisorError.instance("owner_process_info")
    }
    var pathBytes = [CChar](repeating: 0, count: 4096)
    let length = proc_pidpath(pid, &pathBytes, UInt32(pathBytes.count))
    guard length > 0 else {
        throw SupervisorError.instance("owner_process_path")
    }
    let path = String(
        decoding: pathBytes.prefix(Int(length)).map(UInt8.init(bitPattern:)),
        as: UTF8.self
    )
    return ProcessFingerprint(
        executablePath: URL(fileURLWithPath: path)
            .resolvingSymlinksInPath().standardizedFileURL.path,
        startSeconds: info.pbi_start_tvsec,
        startMicroseconds: info.pbi_start_tvusec,
        uid: info.pbi_uid
    )
}

private func storagePaths(_ root: URL) -> [String] {
    let data = root.appendingPathComponent("data", isDirectory: true)
        .standardizedFileURL
    return ["kg.sqlite", "chat.sqlite"].flatMap { name in
        let database = data.appendingPathComponent(name).path
        return [database, database + "-wal", database + "-shm"]
    }
}

private func discoveryTimeNs() throws -> UInt64 {
    var time = timespec()
    guard clock_gettime(CLOCK_REALTIME, &time) == 0 else {
        throw SupervisorError.system("clock_gettime", errno)
    }
    return UInt64(time.tv_sec) * 1_000_000_000 + UInt64(time.tv_nsec)
}

func discoverStorageHolders(_ root: URL) throws -> StorageHolderDiscovery {
    let inspected = storagePaths(root)
    let existing = inspected.filter { FileManager.default.fileExists(atPath: $0) }
    guard !existing.isEmpty else {
        return StorageHolderDiscovery(
            inspectedPaths: inspected,
            inspectedAtNs: try discoveryTimeNs(),
            holders: [:]
        )
    }
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
    process.arguments = ["-Fpn", "--"] + existing
    let output = Pipe()
    let errors = Pipe()
    process.standardOutput = output
    process.standardError = errors
    do { try process.run() }
    catch { throw SupervisorError.instance("holder_discovery_launch") }
    process.waitUntilExit()
    let stdout = output.fileHandleForReading.readDataToEndOfFile()
    let stderr = errors.fileHandleForReading.readDataToEndOfFile()
    guard (process.terminationStatus == 0 || process.terminationStatus == 1),
          stderr.isEmpty,
          let text = String(data: stdout, encoding: .utf8)
    else { throw SupervisorError.instance("holder_discovery") }
    var currentPid: Int32?
    var holders: [Int32: Set<String>] = [:]
    let expectedPaths = Set(existing)
    for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
        guard let field = line.first else {
            throw SupervisorError.instance("holder_output")
        }
        let value = String(line.dropFirst())
        switch field {
        case "p":
            guard let pid = Int32(value), pid > 0 else {
                throw SupervisorError.instance("holder_pid")
            }
            currentPid = pid
            holders[pid] = holders[pid] ?? []
        case "f":
            guard currentPid != nil, !value.isEmpty else {
                throw SupervisorError.instance("holder_fd")
            }
        case "n":
            let matchedPath = expectedPaths.first { expected in
                value == expected
                    || (value.hasPrefix("/private/")
                        && String(value.dropFirst("/private".count)) == expected)
                    || (expected.hasPrefix("/private/")
                        && String(expected.dropFirst("/private".count)) == value)
            }
            guard let pid = currentPid, let matchedPath else {
                throw SupervisorError.instance("holder_path")
            }
            holders[pid, default: []].insert(matchedPath)
        default:
            throw SupervisorError.instance("holder_field")
        }
    }
    guard holders.values.allSatisfy({ !$0.isEmpty }) else {
        throw SupervisorError.instance("holder_incomplete")
    }
    return StorageHolderDiscovery(
        inspectedPaths: inspected,
        inspectedAtNs: try discoveryTimeNs(),
        holders: holders
    )
}
