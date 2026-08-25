import Foundation
import Security

// OntologyLab Keychain helper.
// One JSON object on stdin, one JSON object on stdout. The secret travels
// only in those payloads — never argv, environment, or error text.
// Isolation is whatever the signed binary + Keychain ACL provide; this
// helper does not claim stronger same-user isolation than code signing.

private let maxRequestBytes = 1_048_576
private let tokenPattern = try! NSRegularExpression(
    pattern: "^[a-z0-9][a-z0-9._-]{0,63}$"
)

private struct Request: Decodable {
    let operation: String
    let service: String
    let account: String
    let secret: String?
}

private func emit(ok: Bool, error: String? = nil, secret: String? = nil, status: Int32) -> Never {
    var object: [String: Any] = ["ok": ok]
    if let error {
        object["error"] = error
    }
    if let secret {
        object["secret"] = secret
    }
    guard
        let data = try? JSONSerialization.data(withJSONObject: object, options: []),
        let line = String(data: data, encoding: .utf8)
    else {
        FileHandle.standardOutput.write(Data(#"{"ok":false,"error":"malformed"}"#.utf8))
        FileHandle.standardOutput.write(Data("\n".utf8))
        exit(2)
    }
    FileHandle.standardOutput.write(Data(line.utf8))
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(status)
}

private func fail(_ error: String, status: Int32) -> Never {
    emit(ok: false, error: error, status: status)
}

private func isToken(_ value: String) -> Bool {
    let range = NSRange(value.startIndex..<value.endIndex, in: value)
    return tokenPattern.firstMatch(in: value, options: [], range: range) != nil
}

// Data-protection + WhenUnlockedThisDeviceOnly is in the SDK, but an
// ad-hoc-signed CLI gets errSecMissingEntitlement (-34018). A Developer ID
// / app-signed helper can use that store. We try it first, then the file
// keychain with kSecAttrSynchronizable=false.
private func identityQuery(service: String, account: String, dataProtection: Bool) -> [String: Any] {
    var query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service,
        kSecAttrAccount as String: account,
        kSecAttrSynchronizable as String: false,
    ]
    if dataProtection {
        query[kSecUseDataProtectionKeychain as String] = true
    }
    return query
}

private func addAttributes(service: String, account: String, secret: Data, dataProtection: Bool) -> [String: Any] {
    var attributes = identityQuery(service: service, account: account, dataProtection: dataProtection)
    attributes[kSecValueData as String] = secret
    if dataProtection {
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    }
    return attributes
}

private func isUnsupportedStore(_ status: OSStatus) -> Bool {
    status == errSecMissingEntitlement || status == errSecParam
}

private func mappedFailure(_ status: OSStatus) -> (String, Int32) {
    switch status {
    case errSecItemNotFound:
        return ("not_found", 0)
    case errSecAuthFailed, errSecInteractionNotAllowed, errSecUserCanceled,
         errSecWrPerm, errSecReadOnly:
        return ("unauthorized", 3)
    default:
        return ("refused", 1)
    }
}

private func copySecret(service: String, account: String, dataProtection: Bool) -> (OSStatus, String?) {
    var query = identityQuery(service: service, account: account, dataProtection: dataProtection)
    query[kSecReturnData as String] = true
    query[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecSuccess {
        guard let data = result as? Data, let secret = String(data: data, encoding: .utf8) else {
            return (errSecUnimplemented, nil)
        }
        return (errSecSuccess, secret)
    }
    return (status, nil)
}

private func writeStore(service: String, account: String, payload: Data, dataProtection: Bool) -> OSStatus {
    let query = identityQuery(service: service, account: account, dataProtection: dataProtection)
    let updateStatus = SecItemUpdate(
        query as CFDictionary,
        [kSecValueData as String: payload] as CFDictionary
    )
    if updateStatus == errSecSuccess || isUnsupportedStore(updateStatus) {
        return updateStatus
    }
    if updateStatus != errSecItemNotFound {
        return updateStatus
    }
    var ignored: CFTypeRef?
    let addStatus = SecItemAdd(
        addAttributes(service: service, account: account, secret: payload, dataProtection: dataProtection) as CFDictionary,
        &ignored
    )
    if addStatus == errSecDuplicateItem {
        return SecItemUpdate(
            query as CFDictionary,
            [kSecValueData as String: payload] as CFDictionary
        )
    }
    return addStatus
}

private func doRead(service: String, account: String) {
    var last: OSStatus = errSecItemNotFound
    for dataProtection in [true, false] {
        let (status, secret) = copySecret(service: service, account: account, dataProtection: dataProtection)
        if status == errSecSuccess, let secret {
            emit(ok: true, secret: secret, status: 0)
        }
        if !isUnsupportedStore(status) && status != errSecItemNotFound {
            last = status
            break
        }
        last = status
    }
    let (error, code) = mappedFailure(last)
    if error == "not_found" {
        emit(ok: false, error: error, status: 0)
    }
    fail(error, status: code == 0 ? 1 : code)
}

private func doWrite(service: String, account: String, secret: String) {
    guard !secret.isEmpty else {
        fail("malformed", status: 2)
    }
    let payload = Data(secret.utf8)
    var last: OSStatus = errSecParam
    for dataProtection in [true, false] {
        let status = writeStore(
            service: service, account: account, payload: payload, dataProtection: dataProtection
        )
        if status == errSecSuccess {
            emit(ok: true, status: 0)
        }
        if !isUnsupportedStore(status) {
            last = status
            break
        }
        last = status
    }
    let (error, code) = mappedFailure(last)
    fail(error, status: code == 0 ? 1 : code)
}

private func doDelete(service: String, account: String) {
    var sawSuccess = false
    var last: OSStatus = errSecItemNotFound
    for dataProtection in [true, false] {
        let status = SecItemDelete(
            identityQuery(service: service, account: account, dataProtection: dataProtection) as CFDictionary
        )
        if status == errSecSuccess {
            sawSuccess = true
        } else if !isUnsupportedStore(status) && status != errSecItemNotFound {
            last = status
            let (error, code) = mappedFailure(status)
            fail(error, status: code == 0 ? 1 : code)
        } else {
            last = status
        }
    }
    if sawSuccess || last == errSecItemNotFound || isUnsupportedStore(last) {
        emit(ok: true, status: 0)
    }
    let (error, code) = mappedFailure(last)
    fail(error, status: code == 0 ? 1 : code)
}

private func readRequest() -> Request {
    let data: Data
    do {
        data = try FileHandle.standardInput.readToEnd() ?? Data()
    } catch {
        fail("malformed", status: 2)
    }
    guard !data.isEmpty, data.count <= maxRequestBytes else {
        fail("malformed", status: 2)
    }
    guard let request = try? JSONDecoder().decode(Request.self, from: data) else {
        fail("malformed", status: 2)
    }
    return request
}

private func main() {
    let request = readRequest()
    guard isToken(request.service), isToken(request.account) else {
        fail("malformed", status: 2)
    }
    switch request.operation {
    case "read":
        doRead(service: request.service, account: request.account)
    case "write", "update":
        guard let secret = request.secret else {
            fail("malformed", status: 2)
        }
        doWrite(service: request.service, account: request.account, secret: secret)
    case "delete":
        doDelete(service: request.service, account: request.account)
    default:
        fail("malformed", status: 2)
    }
}

main()
