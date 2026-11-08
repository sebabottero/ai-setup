package com.example.app

import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Test

/** File-scan guardrails for an Android app. They fail the build when a rule from AGENTS.md is broken. */
class ArchitectureTest {

    // Tests run from the app/ module directory.
    private val mainRoot = File("src/main/kotlin/com/example/app")

    private fun kotlinFiles(dir: File): List<File> {
        assertTrue("missing source dir ${dir.path} (tests must run from the app/ module)", dir.isDirectory)
        return dir.walkTopDown().filter { it.isFile && it.extension == "kt" }.toList()
    }

    @Test
    fun domainStaysPure() {
        val violations = kotlinFiles(File(mainRoot, "domain")).flatMap { file ->
            file.readLines().mapIndexedNotNull { i, line ->
                val t = line.trim()
                if (t.startsWith("import android.") || t.startsWith("import androidx.")) {
                    "${file.name}:${i + 1}: $t"
                } else null
            }
        }
        assertTrue(
            "domain/ must not import android.* or androidx.*: domain is pure so it is testable on the JVM. " +
                "Move the Android-dependent code to ui/ or data/. Found:\n" + violations.joinToString("\n"),
            violations.isEmpty(),
        )
    }

    @Test
    fun onlyTheStoreUsesSharedPreferences() {
        val allowed = File(mainRoot, "data/Store.kt").canonicalFile
        val violations = kotlinFiles(File("src/main/kotlin"))
            .filter { it.canonicalFile != allowed }
            .filter { f -> "SharedPreferences" in f.readText() }
            .map { it.path }
        assertTrue(
            "Only data/Store.kt may use SharedPreferences: one place owns the storage format. " +
                "Go through the Store interface instead. Found in:\n" + violations.joinToString("\n"),
            violations.isEmpty(),
        )
    }
}
