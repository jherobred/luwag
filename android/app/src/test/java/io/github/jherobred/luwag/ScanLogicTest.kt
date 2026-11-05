package io.github.jherobred.luwag

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScanLogicTest {
    private fun file(path: String, bytes: Long, modified: Long, bucket: String = "other") =
        FileRec(path, path.substringAfterLast('/'), bytes, modified, bucket)

    @Test
    fun formatsBytesLikeTheWindowsApp() {
        assertEquals("0 B", fmtBytes(0))
        assertEquals("100 MB", fmtBytes(100L * 1024 * 1024))
        assertEquals("1.50 KB", fmtBytes(1536))
    }

    @Test
    fun largeFilesKeepTheBiggest() {
        val files = listOf(file("a", 50, 1), file("b", 200, 1), file("c", 150, 1))
        val large = largeFiles(files, 100, cap = 1)
        assertEquals(listOf("b"), large.map { it.name })
    }

    @Test
    fun oldDownloadsIgnoreOtherFolders() {
        val files = listOf(
            file("Download/a", 10, 1_000, "downloads"),
            file("Pictures/b", 10, 1_000, "pictures"),
        )
        assertEquals(listOf("a"), oldDownloads(files, 5_000).map { it.name })
    }

    @Test
    fun duplicatesKeepTheNewestCopy() {
        val files = listOf(
            file("old", 2_000_000, 10),
            file("new", 2_000_000, 20),
            file("alone", 2_000_000, 30),
        )
        val hashes = mapOf("old" to "aa", "new" to "aa", "alone" to "bb")
        val groups = duplicateGroups(files, hashes)
        assertEquals(1, groups.size)
        assertEquals("new", groups[0].keepPath)
        assertEquals(2, groups[0].files.size)
        assertTrue(hashCandidates(files).none { it.name == "alone" }.not() || groups[0].files.none { it.name == "alone" })
    }
}
