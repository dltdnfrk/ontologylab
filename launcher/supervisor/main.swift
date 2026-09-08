import Darwin
import Foundation

_ = Darwin.umask(0o077)
do {
    let supervisor = Supervisor(configuration: try SupervisorConfiguration.load())
    Darwin.exit(try supervisor.run())
} catch let error as ReadyProtocolError {
    writeStandardError(error.description)
    Darwin.exit(1)
} catch let error as SupervisorError {
    writeStandardError(error.description)
    Darwin.exit(1)
} catch {
    writeStandardError("supervisor_failure")
    Darwin.exit(1)
}
