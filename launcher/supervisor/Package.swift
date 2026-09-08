// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "OntologyLabSupervisor",
    platforms: [.macOS(.v15)],
    targets: [
        .executableTarget(
            name: "OntologyLabSupervisor",
            path: ".",
            exclude: ["Package.swift"]
        )
    ]
)
