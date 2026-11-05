package io.github.jherobred.luwag

import android.content.Context
import android.os.Environment
import android.os.StatFs
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.ArrayDeque
import java.util.UUID

data class VolumeRow(
    val label: String,
    val path: String,
    val total: Long,
    val free: Long,
    val used: Long,
)

data class TrashRec(
    val id: String,
    val name: String,
    val original: String,
    val bytes: Long,
    val at: Long,
)

data class MoveResult(val count: Int, val problems: List<String>)

data class PhoneScan(
    val volumes: List<VolumeRow>,
    val files: List<FileRec>,
    val large: List<FileRec>,
    val downloads: List<FileRec>,
    val dupes: List<DupeGroup>,
    val truncated: Boolean,
    val listed: Boolean,
    val note: String?,
)

class PhoneStore(private val context: Context) {
    private val trashDir = File(context.filesDir, "trash")
    private val manifest = File(trashDir, "manifest.json")
    private val copies = File(trashDir, "files")

    fun canListFiles(): Boolean {
        return if (android.os.Build.VERSION.SDK_INT >= 30) {
            Environment.isExternalStorageManager()
        } else {
            context.checkSelfPermission(android.Manifest.permission.READ_EXTERNAL_STORAGE) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
        }
    }

    fun trash(): List<TrashRec> = load()

    fun scan(): PhoneScan {
        val volumes = volumes()
        if (!canListFiles()) {
            return PhoneScan(
                volumes = volumes,
                files = emptyList(),
                large = emptyList(),
                downloads = emptyList(),
                dupes = emptyList(),
                truncated = false,
                listed = false,
                note = "Free space is measured. File lists need access to shared storage.",
            )
        }
        val files = mutableListOf<FileRec>()
        var truncated = false
        for ((dirType, bucket) in SHARED) {
            val root = Environment.getExternalStoragePublicDirectory(dirType)
            if (root == null || !root.isDirectory) continue
            if (walk(root, bucket, files)) {
                truncated = true
                break
            }
        }
        val cutoff = System.currentTimeMillis() - DOWNLOAD_MS
        val hashes = HashMap<String, String>()
        for (file in hashCandidates(files)) {
            try {
                hashes[file.path] = sampleHash(File(file.path))
            } catch (_: Exception) {
                // An unreadable file stays out of the duplicate list.
            }
        }
        val note = if (truncated) "The list stopped at $FILE_CAP files." else null
        return PhoneScan(
            volumes = volumes,
            files = files,
            large = largeFiles(files, LARGE_MIN),
            downloads = oldDownloads(files, cutoff),
            dupes = duplicateGroups(files, hashes),
            truncated = truncated,
            listed = true,
            note = note,
        )
    }

    fun moveToTrash(paths: List<String>, known: Set<String>): MoveResult {
        trashDir.mkdirs()
        copies.mkdirs()
        val items = load()
        val problems = mutableListOf<String>()
        var moved = 0
        for (path in paths.distinct()) {
            if (path !in known) {
                problems.add("Skipped a file that was not in the last scan.")
                continue
            }
            val src = File(path)
            if (!src.isFile) {
                problems.add("${src.name} is already gone.")
                continue
            }
            val free = freeBytes(context.filesDir)
            if (free < src.length() + COPY_HEADROOM) {
                problems.add("Not enough free space to copy ${src.name}.")
                continue
            }
            val id = UUID.randomUUID().toString()
            val dest = File(copies, id)
            try {
                src.inputStream().use { input -> dest.outputStream().use { output -> input.copyTo(output) } }
                // The original is removed only after the copy length matches.
                if (dest.length() != src.length() || !src.delete()) {
                    dest.delete()
                    problems.add("${src.name} stayed in place.")
                    continue
                }
                items.add(TrashRec(id, src.name, path, dest.length(), System.currentTimeMillis()))
                moved += 1
            } catch (_: Exception) {
                dest.delete()
                problems.add("${src.name} stayed in place.")
            }
        }
        save(items)
        return MoveResult(moved, problems)
    }

    fun restore(ids: Set<String>): MoveResult {
        val keep = mutableListOf<TrashRec>()
        val problems = mutableListOf<String>()
        var restored = 0
        for (item in load()) {
            if (item.id !in ids) {
                keep.add(item)
                continue
            }
            val src = File(copies, item.id)
            val dest = File(item.original)
            if (!src.isFile) {
                problems.add("${item.name} is missing from trash.")
                continue
            }
            if (dest.exists()) {
                problems.add("${item.name} was left in trash because a file is already at the old place.")
                keep.add(item)
                continue
            }
            val parent = dest.parentFile
            if (parent == null || (!parent.isDirectory && !parent.mkdirs())) {
                problems.add("${item.name} stayed in trash.")
                keep.add(item)
                continue
            }
            try {
                src.inputStream().use { input -> dest.outputStream().use { output -> input.copyTo(output) } }
                if (dest.length() != src.length()) {
                    dest.delete()
                    problems.add("${item.name} stayed in trash.")
                    keep.add(item)
                    continue
                }
                src.delete()
                restored += 1
            } catch (_: Exception) {
                if (dest.exists() && dest.length() != src.length()) dest.delete()
                problems.add("${item.name} stayed in trash.")
                keep.add(item)
            }
        }
        save(keep)
        return MoveResult(restored, problems)
    }

    fun emptyTrash() {
        copies.listFiles()?.forEach { it.delete() }
        save(emptyList())
    }

    private fun volumes(): List<VolumeRow> {
        val rows = mutableListOf<VolumeRow>()
        val seen = HashSet<String>()
        fun add(label: String, path: File?) {
            if (path == null || !path.exists()) return
            val key = try {
                path.canonicalPath
            } catch (_: Exception) {
                path.absolutePath
            }
            if (!seen.add(key)) return
            val row = readVolume(label, path) ?: return
            rows.add(row)
        }
        add("Internal storage", Environment.getDataDirectory())
        val shared = Environment.getExternalStorageDirectory()
        if (shared != null && Environment.getExternalStorageState(shared) == Environment.MEDIA_MOUNTED) {
            add("Shared storage", shared)
        }
        return rows
    }

    private fun readVolume(label: String, path: File): VolumeRow? {
        return try {
            val stat = StatFs(path.absolutePath)
            val total = stat.blockCountLong * stat.blockSizeLong
            val free = stat.availableBlocksLong * stat.blockSizeLong
            if (total <= 0) return null
            VolumeRow(label, path.absolutePath, total, free, (total - free).coerceAtLeast(0))
        } catch (_: Exception) {
            null
        }
    }

    private fun walk(root: File, bucket: String, out: MutableList<FileRec>): Boolean {
        val stack = ArrayDeque<File>()
        stack.add(root)
        var dirs = 0
        while (stack.isNotEmpty()) {
            val dir = stack.removeLast()
            dirs += 1
            if (dirs > DIR_CAP || out.size >= FILE_CAP) return true
            val kids = dir.listFiles() ?: continue
            for (kid in kids) {
                if (kid.name == "Android") continue
                try {
                    if (java.nio.file.Files.isSymbolicLink(kid.toPath())) continue
                } catch (_: Exception) {
                    continue
                }
                if (kid.isDirectory) {
                    stack.add(kid)
                } else if (kid.isFile) {
                    if (out.size >= FILE_CAP) return true
                    out.add(FileRec(kid.absolutePath, kid.name, kid.length(), kid.lastModified(), bucket))
                }
            }
        }
        return false
    }

    private fun load(): MutableList<TrashRec> {
        if (!manifest.isFile) return mutableListOf()
        val text = manifest.readText()
        if (text.isBlank()) return mutableListOf()
        val arr = JSONArray(text)
        val out = mutableListOf<TrashRec>()
        for (i in 0 until arr.length()) {
            val obj = arr.getJSONObject(i)
            out.add(
                TrashRec(
                    obj.getString("id"),
                    obj.getString("name"),
                    obj.getString("original"),
                    obj.getLong("bytes"),
                    obj.getLong("at"),
                ),
            )
        }
        return out
    }

    private fun save(items: List<TrashRec>) {
        trashDir.mkdirs()
        val arr = JSONArray()
        for (item in items) {
            arr.put(
                JSONObject()
                    .put("id", item.id)
                    .put("name", item.name)
                    .put("original", item.original)
                    .put("bytes", item.bytes)
                    .put("at", item.at),
            )
        }
        val tmp = File(trashDir, "manifest.json.tmp")
        tmp.writeText(arr.toString())
        if (manifest.exists()) manifest.delete()
        if (!tmp.renameTo(manifest)) {
            manifest.writeText(arr.toString())
            tmp.delete()
        }
    }

    private fun sampleHash(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        RandomAccessFile(file, "r").use { raf ->
            val buf = ByteArray(SAMPLE)
            val first = raf.read(buf)
            if (first > 0) digest.update(buf, 0, first)
            if (raf.length() > SAMPLE) {
                raf.seek(raf.length() - SAMPLE)
                val last = raf.read(buf)
                if (last > 0) digest.update(buf, 0, last)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun freeBytes(path: File): Long {
        val stat = StatFs(path.absolutePath)
        return stat.availableBlocksLong * stat.blockSizeLong
    }

    companion object {
        const val FILE_CAP = 4000
        private const val DIR_CAP = 8000
        private const val SAMPLE = 65536
        private const val LARGE_MIN = 100L * 1024 * 1024
        private const val DOWNLOAD_MS = 30L * 24 * 60 * 60 * 1000
        private const val COPY_HEADROOM = 8L * 1024 * 1024
        private val SHARED = listOf(
            Environment.DIRECTORY_DOWNLOADS to "downloads",
            Environment.DIRECTORY_DCIM to "dcim",
            Environment.DIRECTORY_PICTURES to "pictures",
            Environment.DIRECTORY_MOVIES to "movies",
            Environment.DIRECTORY_MUSIC to "music",
            Environment.DIRECTORY_DOCUMENTS to "documents",
        )
    }
}
