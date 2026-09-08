import Darwin
import Foundation
import Security

private struct StorageCompatibilityContract: Decodable {
    let schema: String
    let releaseVersion: String
    let currentStorageVersion: Int

    enum CodingKeys: String, CodingKey {
        case schema
        case releaseVersion = "release_version"
        case currentStorageVersion = "current_storage_version"
    }

    static func load(resources: URL, releaseVersion: String) throws -> String {
        let path = resources.appendingPathComponent("storage-compatibility.json")
        let data: Data
        do { data = try Data(contentsOf: path) }
        catch { throw SupervisorError.configuration("storage_matrix") }
        let contract: StorageCompatibilityContract
        do { contract = try JSONDecoder().decode(Self.self, from: data) }
        catch { throw SupervisorError.configuration("storage_matrix") }
        guard contract.schema == "ontologylab.storage-compatibility.v1",
              contract.releaseVersion == releaseVersion,
              contract.currentStorageVersion >= 0
        else { throw SupervisorError.configuration("storage_matrix") }
        return String(contract.currentStorageVersion)
    }
}

struct SupervisorConfiguration {
    let resources: URL
    let applicationSupportRoot: URL
    let logsRoot: URL
    let stateRoot: URL
    let backend: URL
    let browserOpener: URL
    let bundleIdentifier: String
    let supervisorExecutablePath: String
    let version: String
    let storageVersion: String
    let readyTimeoutMilliseconds: Int
    let shutdownTimeoutMilliseconds: Int

    static func load() throws -> SupervisorConfiguration {
        let environment = ProcessInfo.processInfo.environment
        let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        let contents = executable.deletingLastPathComponent().deletingLastPathComponent()
        let resources = environment["ONTOLOGYLAB_RESOURCES_DIR"].map(URL.init(fileURLWithPath:))
            ?? contents.appendingPathComponent("Resources", isDirectory: true)
        let defaultApplicationSupport = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        )[0].appendingPathComponent("ontologylab", isDirectory: true)
        let defaultLogs = FileManager.default.urls(
            for: .libraryDirectory, in: .userDomainMask
        )[0].appendingPathComponent("Logs/ontologylab", isDirectory: true)
        let defaultRuntime = FileManager.default.urls(
            for: .cachesDirectory, in: .userDomainMask
        )[0].appendingPathComponent("ontologylab/runtime", isDirectory: true)
        let applicationSupportRoot = environment["ONTOLOGYLAB_APP_SUPPORT_ROOT"]
            .map(URL.init(fileURLWithPath:)) ?? defaultApplicationSupport
        let logsRoot = environment["ONTOLOGYLAB_LOG_ROOT"]
            .map(URL.init(fileURLWithPath:)) ?? defaultLogs
        let stateRoot = environment["ONTOLOGYLAB_STATE_ROOT"]
            .map(URL.init(fileURLWithPath:)) ?? defaultRuntime
        let infoPath = contents.appendingPathComponent("Info.plist")
        guard let info = NSDictionary(contentsOf: infoPath),
              let bundleIdentifier = info["CFBundleIdentifier"] as? String,
              !bundleIdentifier.isEmpty,
              let version = info["CFBundleShortVersionString"] as? String,
              !version.isEmpty,
              environment["ONTOLOGYLAB_APP_VERSION"].map({ $0 == version })
                ?? true
        else { throw SupervisorError.configuration("bundle_identity") }
        let storageVersion = try StorageCompatibilityContract.load(
            resources: resources,
            releaseVersion: version
        )
        let readyTimeout = Int(environment["ONTOLOGYLAB_READY_TIMEOUT_MS"] ?? "15000")
        let shutdownTimeout = Int(environment["ONTOLOGYLAB_SHUTDOWN_TIMEOUT_MS"] ?? "5000")
        guard let readyTimeout, readyTimeout > 0,
              let shutdownTimeout, shutdownTimeout > 0
        else { throw SupervisorError.configuration("timeout") }
        return SupervisorConfiguration(
            resources: resources,
            applicationSupportRoot: applicationSupportRoot,
            logsRoot: logsRoot,
            stateRoot: stateRoot,
            backend: resources.appendingPathComponent("ontologylab-serve-desktop"),
            browserOpener: URL(fileURLWithPath: environment["ONTOLOGYLAB_OPEN_EXECUTABLE"] ?? "/usr/bin/open"),
            bundleIdentifier: bundleIdentifier,
            supervisorExecutablePath: try processFingerprint(getpid()).executablePath,
            version: version,
            storageVersion: storageVersion,
            readyTimeoutMilliseconds: readyTimeout,
            shutdownTimeoutMilliseconds: shutdownTimeout
        )
    }
}

struct InstanceState: Codable {
    let schema: String
    let version: String
    let port: UInt16
    let pid: Int32
    let childPid: Int32
    let nonce: String
    let bundleIdentifier: String
    let supervisorExecutablePath: String
    let backendFingerprint: ProcessFingerprint
}

enum SupervisorError: Error, CustomStringConvertible {
    case configuration(String)
    case instance(String)
    case system(String, Int32)
    case backend(String)

    var description: String {
        switch self {
        case .configuration(let member): return "configuration_refused member=\(member)"
        case .instance(let member): return "instance_refused member=\(member)"
        case .system(let operation, let code): return "system_failure operation=\(operation) errno=\(code)"
        case .backend(let member): return "backend_refused member=\(member)"
        }
    }
}

enum LockResult {
    case acquired(Int32)
    case occupied(Int32, Int32)
}

final class Supervisor {
    private let configuration: SupervisorConfiguration

    init(configuration: SupervisorConfiguration) {
        self.configuration = configuration
    }

    func run() throws -> Int32 {
        try prepareStateRoot(configuration.stateRoot)
        switch try acquireInstanceLock(configuration.stateRoot) {
        case .occupied(let descriptor, let owner):
            defer { Darwin.close(descriptor) }
            let state = try validatedInstanceState(
                root: configuration.stateRoot,
                version: configuration.version,
                lockOwner: owner
            )
            guard openBrowser(port: state.port) else {
                throw SupervisorError.instance("browser")
            }
            return 0
        case .acquired(let lockDescriptor):
            defer { Darwin.close(lockDescriptor) }
            return try runOwnedInstance()
        }
    }

    private func runOwnedInstance() throws -> Int32 {
        let listener = try bindLoopbackListener()
        defer { Darwin.close(listener.descriptor) }
        let nonce = try makeNonce()
        let quiescenceReceipt = try prepareStorageQuiescence(
            configuration: configuration,
            nonce: nonce
        )
        defer { try? FileManager.default.removeItem(at: quiescenceReceipt) }
        var descriptors: [Int32] = [0, 0]
        guard Darwin.pipe(&descriptors) == 0 else {
            throw SupervisorError.system("pipe", errno)
        }
        let reader = ReadinessReader(fileDescriptor: descriptors[0])
        let readyWriter = descriptors[1]
        setCloseOnExec(descriptors[0], enabled: true)
        setCloseOnExec(readyWriter, enabled: false)
        setCloseOnExec(listener.descriptor, enabled: false)
        let child = try launchBackend(
            listener: listener.descriptor,
            readyWriter: readyWriter,
            nonce: nonce,
            quiescenceReceipt: quiescenceReceipt
        )
        Darwin.close(readyWriter)
        let monitor = ChildExitMonitor()
        child.terminationHandler = { _ in monitor.markExited() }
        let shutdown = ShutdownState()
        let signalSource = installTerminationHandler(
            child: child,
            monitor: monitor,
            shutdown: shutdown
        )
        defer { signalSource.cancel() }
        do {
            let line = try reader.readLine(
                timeoutMilliseconds: configuration.readyTimeoutMilliseconds
            )
            let receipt = try parseReadyLine(
                line,
                expecting: ReadyExpectation(
                    version: configuration.version,
                    port: listener.port,
                    nonce: nonce,
                    storageVersion: configuration.storageVersion
                )
            )
            let statePath = configuration.stateRoot.appendingPathComponent("instance.json")
            let backendFingerprint = try? processFingerprint(child.processIdentifier)
            if let backendFingerprint, child.isRunning {
                try persistInstanceState(
                    InstanceState(
                        schema: "ontologylab.instance.v2",
                        version: configuration.version,
                        port: receipt.port,
                        pid: getpid(),
                        childPid: child.processIdentifier,
                        nonce: nonce,
                        bundleIdentifier: configuration.bundleIdentifier,
                        supervisorExecutablePath: configuration.supervisorExecutablePath,
                        backendFingerprint: backendFingerprint
                    ),
                    root: configuration.stateRoot
                )
            }
            defer { try? FileManager.default.removeItem(at: statePath) }
            guard openBrowser(port: receipt.port) else {
                throw SupervisorError.backend("browser")
            }
            _ = monitor.wait(milliseconds: nil)
            return shutdown.requested ? 0 : child.terminationStatus
        } catch {
            stopExactChild(
                child,
                monitor: monitor,
                timeoutMilliseconds: configuration.shutdownTimeoutMilliseconds
            )
            throw error
        }
    }

    private func launchBackend(
        listener: Int32,
        readyWriter: Int32,
        nonce: String,
        quiescenceReceipt: URL
    ) throws -> Process {
        guard FileManager.default.isExecutableFile(atPath: configuration.backend.path) else {
            throw SupervisorError.configuration("backend")
        }
        let child = Process()
        child.executableURL = configuration.backend
        var environment = ProcessInfo.processInfo.environment
        environment["ONTOLOGYLAB_LISTENER_FD"] = "0"
        environment["ONTOLOGYLAB_READY_FD"] = "1"
        environment["ONTOLOGYLAB_NONCE"] = nonce
        environment["ONTOLOGYLAB_APP_VERSION"] = configuration.version
        environment["ONTOLOGYLAB_STORAGE_VERSION"] = configuration.storageVersion
        environment["ONTOLOGYLAB_SUPERVISOR_PID"] = String(getpid())
        environment["ONTOLOGYLAB_QUIESCENCE_RECEIPT"] = quiescenceReceipt.path
        environment["ONTOLOGYLAB_RESOURCES_DIR"] = configuration.resources.path
        environment["ONTOLOGYLAB_DATA_DIR"] = configuration.applicationSupportRoot.appendingPathComponent("data").path
        environment["ONTOLOGYLAB_PACKS_DIR"] = configuration.applicationSupportRoot.appendingPathComponent("packs").path
        environment["ONTOLOGYLAB_LOG_DIR"] = configuration.logsRoot.path
        environment["ONTOLOGYLAB_RUNTIME_DIR"] = configuration.stateRoot.path
        environment["ONTOLOGYLAB_KEYCHAIN_HELPER"] = configuration.resources.appendingPathComponent("keychain-helper").path
        let requirementPath = configuration.resources.appendingPathComponent("keychain-helper.requirement")
        if FileManager.default.fileExists(atPath: requirementPath.path) {
            let requirement = try String(contentsOf: requirementPath, encoding: .utf8)
            environment["ONTOLOGYLAB_KEYCHAIN_HELPER_REQUIREMENT"] = requirement.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        child.environment = environment
        child.standardInput = FileHandle(fileDescriptor: listener, closeOnDealloc: false)
        child.standardOutput = FileHandle(fileDescriptor: readyWriter, closeOnDealloc: false)
        do { try child.run() }
        catch { throw SupervisorError.backend("launch") }
        return child
    }

    private func installTerminationHandler(
        child: Process,
        monitor: ChildExitMonitor,
        shutdown: ShutdownState
    ) -> DispatchSourceSignal {
        Darwin.signal(SIGTERM, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        source.setEventHandler { [configuration] in
            shutdown.markRequested()
            stopExactChild(
                child,
                monitor: monitor,
                timeoutMilliseconds: configuration.shutdownTimeoutMilliseconds
            )
        }
        source.resume()
        return source
    }

    private func openBrowser(port: UInt16) -> Bool {
        let url = "http://127.0.0.1:\(port)/"
        if runBrowser(arguments: ["-b", "at.studio.AsideBrowser", url]) == 0 {
            return true
        }
        return runBrowser(arguments: [url]) == 0
    }

    private func runBrowser(arguments: [String]) -> Int32 {
        let process = Process()
        process.executableURL = configuration.browserOpener
        process.arguments = arguments
        do { try process.run() }
        catch { return -1 }
        process.waitUntilExit()
        return process.terminationStatus
    }
}
