import Darwin
import Foundation

struct VerifiedBackendOwner: Codable {
    let pid: Int32
    let version: String
    let bundleIdentifier: String
    let fingerprint: ProcessFingerprint
}

private struct StorageQuiescenceReceipt: Codable {
    let schemaName: String
    let proofKind: String
    let supervisorPid: Int32
    let nonce: String
    let inspectedPaths: [String]
    let inspectedAtNs: UInt64
    let initialHolderPids: [Int32]
    let finalHolderPids: [Int32]
    let verifiedOwner: VerifiedBackendOwner?
    let signals: [String]
    let exitObserved: Bool

    enum CodingKeys: String, CodingKey {
        case schemaName = "schema_name"
        case proofKind = "proof_kind"
        case supervisorPid = "supervisor_pid"
        case nonce
        case inspectedPaths = "inspected_paths"
        case inspectedAtNs = "inspected_at_ns"
        case initialHolderPids = "initial_holder_pids"
        case finalHolderPids = "final_holder_pids"
        case verifiedOwner = "verified_owner"
        case signals
        case exitObserved = "exit_observed"
    }
}

private func loadOwnerRecord(_ root: URL) throws -> InstanceState? {
    let path = root.appendingPathComponent("instance.json")
    var metadata = stat()
    if lstat(path.path, &metadata) != 0 {
        guard errno == ENOENT else {
            throw SupervisorError.instance("owner_record_access")
        }
        return nil
    }
    guard (metadata.st_mode & S_IFMT) == S_IFREG,
          (metadata.st_mode & 0o777) == 0o600,
          metadata.st_uid == getuid()
    else { throw SupervisorError.instance("owner_record_permissions") }
    let data: Data
    do { data = try Data(contentsOf: path, options: .uncached) }
    catch { throw SupervisorError.instance("owner_record_read") }
    let expectedKeys = Set([
        "schema", "version", "port", "pid", "childPid", "nonce",
        "bundleIdentifier", "supervisorExecutablePath", "backendFingerprint",
    ])
    guard let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          Set(raw.keys) == expectedKeys,
          let state = try? JSONDecoder().decode(InstanceState.self, from: data)
    else { throw SupervisorError.instance("owner_record_invalid") }
    return state
}

private func validateOwnerIdentity(
    _ state: InstanceState,
    configuration: SupervisorConfiguration
) throws {
    var recordedInfo = stat()
    var currentInfo = stat()
    let recordedPath = state.supervisorExecutablePath
    let currentPath = configuration.supervisorExecutablePath
    guard state.version == configuration.version,
          state.bundleIdentifier == configuration.bundleIdentifier,
          recordedPath == currentPath,
          lstat(recordedPath, &recordedInfo) == 0,
          (recordedInfo.st_mode & S_IFMT) == S_IFREG,
          stat(currentPath, &currentInfo) == 0,
          recordedInfo.st_dev == currentInfo.st_dev,
          recordedInfo.st_ino == currentInfo.st_ino
    else { throw SupervisorError.instance("owner_identity") }
}

private func waitForExit(_ pid: Int32, timeoutMilliseconds: Int) throws -> Bool {
    if Darwin.kill(pid, 0) != 0, errno == ESRCH { return true }
    let queue = kqueue()
    guard queue >= 0 else { throw SupervisorError.system("kqueue", errno) }
    defer { Darwin.close(queue) }
    var change = kevent(
        ident: UInt(pid),
        filter: Int16(EVFILT_PROC),
        flags: UInt16(EV_ADD | EV_ONESHOT),
        fflags: UInt32(NOTE_EXIT),
        data: 0,
        udata: nil
    )
    guard kevent(queue, &change, 1, nil, 0, nil) == 0 else {
        if Darwin.kill(pid, 0) != 0, errno == ESRCH { return true }
        throw SupervisorError.system("kevent_register", errno)
    }
    var event = kevent()
    var timeout = timespec(
        tv_sec: timeoutMilliseconds / 1_000,
        tv_nsec: (timeoutMilliseconds % 1_000) * 1_000_000
    )
    let count = kevent(queue, nil, 0, &event, 1, &timeout)
    if count == 1 { return true }
    if count == 0 { return false }
    throw SupervisorError.system("kevent_wait", errno)
}

private func stopRecordedBackend(
    _ owner: VerifiedBackendOwner,
    timeoutMilliseconds: Int
) throws -> [String] {
    guard try processFingerprint(owner.pid) == owner.fingerprint else {
        throw SupervisorError.instance("owner_fingerprint_mismatch")
    }
    guard Darwin.kill(owner.pid, SIGTERM) == 0 else {
        throw SupervisorError.system("signal_old_backend", errno)
    }
    if try waitForExit(owner.pid, timeoutMilliseconds: timeoutMilliseconds) {
        return ["SIGTERM", "exit-observed"]
    }
    guard try processFingerprint(owner.pid) == owner.fingerprint else {
        throw SupervisorError.instance("owner_pid_reused")
    }
    guard Darwin.kill(owner.pid, SIGKILL) == 0 else {
        throw SupervisorError.system("kill_old_backend", errno)
    }
    guard try waitForExit(owner.pid, timeoutMilliseconds: timeoutMilliseconds) else {
        throw SupervisorError.instance("old_backend_hung")
    }
    return ["SIGTERM", "SIGKILL", "exit-observed"]
}

private func writeQuiescenceReceipt(
    _ receipt: StorageQuiescenceReceipt,
    root: URL
) throws -> URL {
    let path = root.appendingPathComponent("quiescence.json")
    do {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(receipt).write(to: path, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600], ofItemAtPath: path.path
        )
    } catch { throw SupervisorError.instance("quiescence_write") }
    return path
}

func prepareStorageQuiescence(
    configuration: SupervisorConfiguration,
    nonce: String
) throws -> URL {
    let initial = try discoverStorageHolders(configuration.applicationSupportRoot)
    let holderPids = initial.holders.keys.sorted()
    let record = try loadOwnerRecord(configuration.stateRoot)
    let owner: VerifiedBackendOwner?
    let signals: [String]
    switch (holderPids.isEmpty, record) {
    case (true, nil):
        owner = nil
        signals = []
    case (false, nil):
        throw SupervisorError.instance("unrecorded_backend")
    case (true, .some):
        throw SupervisorError.instance("stale_owner_record")
    case (false, .some(let state)):
        guard state.schema == "ontologylab.instance.v2",
              holderPids == [state.childPid]
        else { throw SupervisorError.instance("owner_holder_mismatch") }
        try validateOwnerIdentity(state, configuration: configuration)
        let actual = try processFingerprint(state.childPid)
        guard actual == state.backendFingerprint else {
            throw SupervisorError.instance("owner_fingerprint_mismatch")
        }
        let verifiedOwner = VerifiedBackendOwner(
            pid: state.childPid,
            version: state.version,
            bundleIdentifier: state.bundleIdentifier,
            fingerprint: state.backendFingerprint
        )
        owner = verifiedOwner
        signals = try stopRecordedBackend(
            verifiedOwner,
            timeoutMilliseconds: configuration.shutdownTimeoutMilliseconds
        )
    }
    let final = try discoverStorageHolders(configuration.applicationSupportRoot)
    guard final.holders.isEmpty else {
        throw SupervisorError.instance("holder_remained")
    }
    if record != nil {
        do { try FileManager.default.removeItem(
            at: configuration.stateRoot.appendingPathComponent("instance.json")
        ) }
        catch { throw SupervisorError.instance("owner_record_remove") }
    }
    return try writeQuiescenceReceipt(
        StorageQuiescenceReceipt(
            schemaName: "ontologylab.storage-quiescence.v2",
            proofKind: owner == nil ? "no_existing_backend" : "stopped_backend",
            supervisorPid: getpid(),
            nonce: nonce,
            inspectedPaths: final.inspectedPaths,
            inspectedAtNs: final.inspectedAtNs,
            initialHolderPids: holderPids,
            finalHolderPids: final.holders.keys.sorted(),
            verifiedOwner: owner,
            signals: signals,
            exitObserved: owner != nil
        ),
        root: configuration.stateRoot
    )
}
