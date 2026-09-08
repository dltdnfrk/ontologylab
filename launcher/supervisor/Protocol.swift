import Foundation

struct ReadyExpectation {
    let version: String
    let port: UInt16
    let nonce: String
    let storageVersion: String
}

struct ReadyReceipt {
    let port: UInt16
}

enum ReadyProtocolError: Error, CustomStringConvertible {
    case invalid(String)

    var description: String {
        switch self {
        case .invalid(let member):
            return "readiness_refused member=\(member)"
        }
    }
}

private enum JSONAtom {
    case string(String)
    case integer(Int)
}

private struct FlatJSONParser {
    private let bytes: [UInt8]
    private var index = 0

    init(_ data: Data) {
        bytes = Array(data)
    }

    mutating func parse() throws -> [String: JSONAtom] {
        skipWhitespace()
        try consume(123)
        var values: [String: JSONAtom] = [:]
        skipWhitespace()
        if peek() == 125 {
            index += 1
        } else {
            while true {
                let key = try parseString()
                guard values[key] == nil else {
                    throw ReadyProtocolError.invalid("duplicate_key")
                }
                skipWhitespace()
                try consume(58)
                skipWhitespace()
                values[key] = try parseAtom()
                skipWhitespace()
                if peek() == 125 {
                    index += 1
                    break
                }
                try consume(44)
                skipWhitespace()
            }
        }
        skipWhitespace()
        guard index == bytes.count else {
            throw ReadyProtocolError.invalid("trailing_bytes")
        }
        return values
    }

    private mutating func parseAtom() throws -> JSONAtom {
        if peek() == 34 {
            return .string(try parseString())
        }
        let start = index
        if peek() == 45 { index += 1 }
        while let byte = peek(), byte >= 48, byte <= 57 { index += 1 }
        guard index > start,
              let text = String(bytes: bytes[start..<index], encoding: .utf8),
              let value = Int(text)
        else {
            throw ReadyProtocolError.invalid("value_type")
        }
        return .integer(value)
    }

    private mutating func parseString() throws -> String {
        try consume(34)
        let start = index
        while let byte = peek(), byte != 34 {
            guard byte >= 32, byte != 92 else {
                throw ReadyProtocolError.invalid("string_encoding")
            }
            index += 1
        }
        guard peek() == 34,
              let value = String(bytes: bytes[start..<index], encoding: .utf8)
        else {
            throw ReadyProtocolError.invalid("string")
        }
        index += 1
        return value
    }

    private mutating func consume(_ expected: UInt8) throws {
        guard peek() == expected else {
            throw ReadyProtocolError.invalid("json")
        }
        index += 1
    }

    private mutating func skipWhitespace() {
        while let byte = peek(), [9, 10, 13, 32].contains(byte) { index += 1 }
    }

    private func peek() -> UInt8? {
        index < bytes.count ? bytes[index] : nil
    }
}

func parseReadyLine(_ data: Data, expecting expected: ReadyExpectation) throws -> ReadyReceipt {
    guard data.count <= 4096 else { throw ReadyProtocolError.invalid("line_size") }
    var parser = FlatJSONParser(data)
    let values = try parser.parse()
    let required = Set(["schema", "version", "port", "nonce", "storage_version"])
    guard Set(values.keys) == required else { throw ReadyProtocolError.invalid("keys") }
    guard case .string("ontologylab-ready-v1") = values["schema"] else {
        throw ReadyProtocolError.invalid("schema")
    }
    guard case .string(expected.version) = values["version"] else {
        throw ReadyProtocolError.invalid("version")
    }
    guard case .string(expected.nonce) = values["nonce"] else {
        throw ReadyProtocolError.invalid("nonce")
    }
    guard case .string(expected.storageVersion) = values["storage_version"] else {
        throw ReadyProtocolError.invalid("storage_version")
    }
    guard case .integer(let rawPort) = values["port"],
          rawPort > 0,
          rawPort <= Int(UInt16.max),
          UInt16(rawPort) == expected.port
    else {
        throw ReadyProtocolError.invalid("port")
    }
    return ReadyReceipt(port: UInt16(rawPort))
}
