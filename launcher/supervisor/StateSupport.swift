import Darwin
import Foundation
import Security

struct BoundListener {
    let descriptor: Int32
    let port: UInt16
}

func prepareStateRoot(_ root: URL) throws {
    var metadata = stat()
    if lstat(root.path, &metadata) == 0 {
        guard (metadata.st_mode & S_IFMT) == S_IFDIR else {
            throw SupervisorError.instance("state_symlink")
        }
        guard (metadata.st_mode & 0o777) == 0o700 else {
            throw SupervisorError.instance("state_permissions")
        }
        return
    }
    guard errno == ENOENT else { throw SupervisorError.instance("state_root") }
    do {
        try FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: root.path
        )
    } catch {
        throw SupervisorError.instance("state_root")
    }
}

func acquireInstanceLock(_ root: URL) throws -> LockResult {
    let path = root.appendingPathComponent("supervisor.lock").path
    let descriptor = Darwin.open(path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0o600)
    guard descriptor >= 0 else { throw SupervisorError.system("open_lock", errno) }
    var metadata = stat()
    guard fstat(descriptor, &metadata) == 0,
          (metadata.st_mode & 0o777) == 0o600
    else {
        Darwin.close(descriptor)
        throw SupervisorError.instance("lock_permissions")
    }
    var record = flock()
    record.l_type = Int16(F_WRLCK)
    record.l_whence = Int16(SEEK_SET)
    if fcntl(descriptor, F_SETLK, &record) == 0 {
        return .acquired(descriptor)
    }
    guard errno == EACCES || errno == EAGAIN else {
        let code = errno
        Darwin.close(descriptor)
        throw SupervisorError.system("lock", code)
    }
    record.l_type = Int16(F_WRLCK)
    guard fcntl(descriptor, F_GETLK, &record) == 0,
          record.l_type != Int16(F_UNLCK),
          record.l_pid > 0
    else {
        Darwin.close(descriptor)
        throw SupervisorError.instance("lock_owner")
    }
    return .occupied(descriptor, record.l_pid)
}

func validatedInstanceState(
    root: URL,
    version: String,
    lockOwner: Int32
) throws -> InstanceState {
    let path = root.appendingPathComponent("instance.json")
    let state: InstanceState
    var metadata = stat()
    guard lstat(path.path, &metadata) == 0,
          (metadata.st_mode & S_IFMT) == S_IFREG,
          (metadata.st_mode & 0o777) == 0o600
    else { throw SupervisorError.instance("state_permissions") }
    do {
        let data = try Data(contentsOf: path, options: .uncached)
        state = try JSONDecoder().decode(InstanceState.self, from: data)
    } catch {
        throw SupervisorError.instance("state")
    }
    let validNonce = state.nonce.count == 32 && state.nonce.allSatisfy {
        $0.isNumber || ("a"..."f").contains(String($0))
    }
    var ownerPathBytes = [CChar](repeating: 0, count: 4096)
    let ownerPathLength = proc_pidpath(
        lockOwner,
        &ownerPathBytes,
        UInt32(ownerPathBytes.count)
    )
    let ownerPath = ownerPathLength > 0
        ? String(
            decoding: ownerPathBytes.prefix(Int(ownerPathLength)).map(UInt8.init(bitPattern:)),
            as: UTF8.self
        )
        : ""
    let currentPath = URL(fileURLWithPath: CommandLine.arguments[0])
        .resolvingSymlinksInPath().standardizedFileURL.path
    let canonicalOwnerPath = URL(fileURLWithPath: ownerPath)
        .resolvingSymlinksInPath().standardizedFileURL.path
    let backendFingerprint = try processFingerprint(state.childPid)
    guard state.schema == "ontologylab.instance.v2",
          state.version == version,
          state.pid == lockOwner,
          state.port > 0,
          validNonce,
          ownerPathLength > 0,
          canonicalOwnerPath == currentPath,
          backendFingerprint == state.backendFingerprint,
          Darwin.kill(state.pid, 0) == 0
    else {
        throw SupervisorError.instance("state_identity")
    }
    return state
}

func persistInstanceState(_ state: InstanceState, root: URL) throws {
    let path = root.appendingPathComponent("instance.json")
    do {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(state).write(to: path, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: path.path
        )
    } catch {
        throw SupervisorError.instance("state_write")
    }
}

func makeNonce() throws -> String {
    var bytes = [UInt8](repeating: 0, count: 16)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
        throw SupervisorError.configuration("nonce")
    }
    return bytes.map { String(format: "%02x", $0) }.joined()
}

func setCloseOnExec(_ descriptor: Int32, enabled: Bool) {
    let flags = fcntl(descriptor, F_GETFD)
    guard flags >= 0 else { return }
    _ = fcntl(descriptor, F_SETFD, enabled ? flags | FD_CLOEXEC : flags & ~FD_CLOEXEC)
}

func bindLoopbackListener() throws -> BoundListener {
    let descriptor = Darwin.socket(AF_INET, SOCK_STREAM, 0)
    guard descriptor >= 0 else { throw SupervisorError.system("socket", errno) }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = 0
    guard inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1 else {
        Darwin.close(descriptor)
        throw SupervisorError.system("inet_pton", errno)
    }
    let bound = withUnsafePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    guard bound == 0, Darwin.listen(descriptor, SOMAXCONN) == 0 else {
        let code = errno
        Darwin.close(descriptor)
        throw SupervisorError.system("bind", code)
    }
    var local = sockaddr_in()
    var length = socklen_t(MemoryLayout<sockaddr_in>.size)
    let named = withUnsafeMutablePointer(to: &local) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            Darwin.getsockname(descriptor, $0, &length)
        }
    }
    guard named == 0 else {
        let code = errno
        Darwin.close(descriptor)
        throw SupervisorError.system("getsockname", code)
    }
    return BoundListener(descriptor: descriptor, port: UInt16(bigEndian: local.sin_port))
}
