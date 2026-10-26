// Prints one JSON line per FSEvents event below the folder given as argument,
// with file-level events and no coalescing delay. Started by watch-locks.py.
import CoreServices
import Foundation

let flagNames: [(Int, String)] = [
    (kFSEventStreamEventFlagItemCreated, "created"),
    (kFSEventStreamEventFlagItemRemoved, "removed"),
    (kFSEventStreamEventFlagItemRenamed, "renamed"),
    (kFSEventStreamEventFlagItemModified, "modified"),
    (kFSEventStreamEventFlagItemInodeMetaMod, "inode_meta_mod"),
    (kFSEventStreamEventFlagItemChangeOwner, "change_owner"),
    (kFSEventStreamEventFlagItemXattrMod, "xattr_mod"),
    (kFSEventStreamEventFlagItemIsFile, "is_file"),
    (kFSEventStreamEventFlagItemIsDir, "is_dir"),
    (kFSEventStreamEventFlagMustScanSubDirs, "must_scan_subdirs"),
    (kFSEventStreamEventFlagRootChanged, "root_changed"),
]

let callback: FSEventStreamCallback = { _, _, count, paths, flags, ids in
    let paths = unsafeBitCast(paths, to: NSArray.self) as? [String] ?? []
    for i in 0..<count {
        let raw = Int(flags[i])
        let entry: [String: Any] = [
            "file": (paths[i] as NSString).lastPathComponent,
            "flags": flagNames.filter { raw & $0.0 != 0 }.map { $0.1 },
            "id": ids[i],
        ]
        if let data = try? JSONSerialization.data(withJSONObject: entry),
           let line = String(data: data, encoding: .utf8) {
            print(line)
        }
    }
    fflush(stdout)
}

var context = FSEventStreamContext(
    version: 0, info: nil, retain: nil, release: nil, copyDescription: nil)
let createFlags = kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagNoDefer
    | kFSEventStreamCreateFlagUseCFTypes
guard let stream = FSEventStreamCreate(
    nil, callback, &context, [CommandLine.arguments[1]] as CFArray,
    FSEventStreamEventId(kFSEventStreamEventIdSinceNow), 0.05,
    FSEventStreamCreateFlags(createFlags))
else { exit(1) }
FSEventStreamSetDispatchQueue(stream, DispatchQueue.main)
FSEventStreamStart(stream)
dispatchMain()
