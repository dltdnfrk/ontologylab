import Darwin
import Foundation

final class ShutdownState: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false

    func markRequested() {
        lock.lock()
        value = true
        lock.unlock()
    }

    var requested: Bool {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

final class ChildExitMonitor: @unchecked Sendable {
    private let condition = NSCondition()
    private var exited = false

    func markExited() {
        condition.lock()
        exited = true
        condition.broadcast()
        condition.unlock()
    }

    func wait(milliseconds: Int?) -> Bool {
        condition.lock()
        defer { condition.unlock() }
        if exited { return true }
        guard let milliseconds else {
            while !exited { condition.wait() }
            return true
        }
        let deadline = Date(timeIntervalSinceNow: Double(milliseconds) / 1_000)
        while !exited, condition.wait(until: deadline) {}
        return exited
    }
}

final class ReadinessReader: @unchecked Sendable {
    private let handle: FileHandle
    private let lock = NSLock()
    private let completed = DispatchSemaphore(value: 0)
    private var buffer = Data()
    private var result: Result<Data, ReadyProtocolError>?

    init(fileDescriptor: Int32) {
        handle = FileHandle(fileDescriptor: fileDescriptor, closeOnDealloc: true)
    }

    func readLine(timeoutMilliseconds: Int) throws -> Data {
        handle.readabilityHandler = { [weak self] readable in
            guard let self else { return }
            let data = readable.availableData
            self.accept(data)
        }
        if completed.wait(timeout: .now() + .milliseconds(timeoutMilliseconds)) == .timedOut {
            finish(.failure(.invalid("timeout")))
        }
        handle.readabilityHandler = nil
        guard let result else { throw ReadyProtocolError.invalid("reader") }
        return try result.get()
    }

    private func accept(_ data: Data) {
        lock.lock()
        guard result == nil else {
            lock.unlock()
            return
        }
        if data.isEmpty {
            guard let newline = buffer.firstIndex(of: 10),
                  buffer.index(after: newline) == buffer.endIndex
            else {
                result = .failure(.invalid("eof"))
                lock.unlock()
                completed.signal()
                return
            }
            result = .success(Data(buffer[..<newline]))
            lock.unlock()
            completed.signal()
            return
        }
        buffer.append(data)
        if buffer.count > 4097 {
            result = .failure(.invalid("line_size"))
            lock.unlock()
            completed.signal()
            return
        }
        if let newline = buffer.firstIndex(of: 10),
           buffer.index(after: newline) != buffer.endIndex {
            result = .failure(.invalid("extra_line"))
            lock.unlock()
            completed.signal()
            return
        }
        lock.unlock()
    }

    private func finish(_ value: Result<Data, ReadyProtocolError>) {
        lock.lock()
        guard result == nil else {
            lock.unlock()
            return
        }
        result = value
        lock.unlock()
        completed.signal()
    }
}

func writeStandardError(_ message: String) {
    let line = Data((message + "\n").utf8)
    FileHandle.standardError.write(line)
}

func stopExactChild(
    _ child: Process,
    monitor: ChildExitMonitor,
    timeoutMilliseconds: Int
) {
    guard child.isRunning else { return }
    let pid = child.processIdentifier
    _ = Darwin.kill(pid, SIGTERM)
    if !monitor.wait(milliseconds: timeoutMilliseconds), child.isRunning {
        _ = Darwin.kill(pid, SIGKILL)
        writeStandardError("forced_kill_pid=\(pid)")
        _ = monitor.wait(milliseconds: nil)
    }
}
