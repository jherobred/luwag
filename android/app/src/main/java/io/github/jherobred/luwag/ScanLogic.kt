package io.github.jherobred.luwag

data class FileRec(
    val path: String,
    val name: String,
    val bytes: Long,
    val modified: Long,
    val bucket: String,
)

data class DupeGroup(
    val bytes: Long,
    val files: List<FileRec>,
    val keepPath: String,
)

fun fmtBytes(n: Long): String {
    val sign = if (n < 0) "-" else ""
    var value = kotlin.math.abs(n).toDouble()
    val units = arrayOf("B", "KB", "MB", "GB", "TB")
    var idx = 0
    while (value >= 1024 && idx < units.lastIndex) {
        value /= 1024.0
        idx += 1
    }
    val text = when {
        idx == 0 || value >= 100 -> "%.0f".format(value)
        value >= 10 -> "%.1f".format(value)
        else -> "%.2f".format(value)
    }
    return sign + text + " " + units[idx]
}

fun largeFiles(files: List<FileRec>, minBytes: Long, cap: Int = 200): List<FileRec> =
    files.filter { it.bytes >= minBytes }.sortedByDescending { it.bytes }.take(cap)

fun oldDownloads(files: List<FileRec>, olderThanEpochMs: Long): List<FileRec> =
    files.filter { it.bucket == "downloads" && it.modified in 1 until olderThanEpochMs }
        .sortedBy { it.modified }

fun hashCandidates(files: List<FileRec>): List<FileRec> =
    files.groupBy { it.bytes }
        .filter { (size, group) -> size in 1_048_576L..2_147_483_648L && group.size in 2..12 }
        .values
        .flatten()

fun duplicateGroups(files: List<FileRec>, hashes: Map<String, String>, cap: Int = 80): List<DupeGroup> {
    val groups = mutableListOf<DupeGroup>()
    for (candidate in hashCandidates(files).groupBy { it.bytes }.values) {
        val hashed = candidate.mapNotNull { file -> hashes[file.path]?.let { file to it } }
        for (same in hashed.groupBy { it.second }.values) {
            if (same.size !in 2..8) continue
            val ordered = same.map { it.first }.sortedByDescending { it.modified }
            groups.add(DupeGroup(ordered.first().bytes, ordered, ordered.first().path))
        }
    }
    return groups.sortedByDescending { it.bytes * (it.files.size - 1) }.take(cap)
}
