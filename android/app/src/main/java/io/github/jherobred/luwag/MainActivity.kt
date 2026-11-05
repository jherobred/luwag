package io.github.jherobred.luwag

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.Image
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private enum class Page { Overview, Large, Downloads, Dupes, Trash, Settings }

private val Ink = Color(0xFF151413)
private val Muted = Color(0xFF66645F)
private val MutedDark = Color(0xFFC8C2B8)
private val Bg = Color(0xFFF7F6F4)
private val BgDark = Color(0xFF0F0F10)
private val Card = Color(0xFFFFFFFF)
private val CardDark = Color(0xFF18181A)
private val Accent = Color(0xFFB84C0C)
private val AccentDark = Color(0xFFFF8A3D)
private val Track = Color(0xFFE4E1DB)
private val TrackDark = Color(0xFF2A2928)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { LuwagApp() }
    }
}

@Composable
private fun LuwagApp() {
    val context = LocalContext.current
    val store = remember { PhoneStore(context.applicationContext) }
    val prefs = remember { context.getSharedPreferences("luwag", android.content.Context.MODE_PRIVATE) }
    val dark = isSystemInDarkTheme()
    val scheme = if (dark) {
        darkColorScheme(
            primary = AccentDark,
            onPrimary = Ink,
            background = BgDark,
            onBackground = Bg,
            surface = CardDark,
            onSurface = Bg,
            surfaceVariant = CardDark,
            onSurfaceVariant = MutedDark,
        )
    } else {
        lightColorScheme(
            primary = Accent,
            onPrimary = Color.White,
            background = Bg,
            onBackground = Ink,
            surface = Card,
            onSurface = Ink,
            surfaceVariant = Bg,
            onSurfaceVariant = Muted,
        )
    }
    val ink = scheme.onBackground
    val muted = scheme.onSurfaceVariant
    val card = scheme.surface
    val accent = scheme.primary
    val track = if (dark) TrackDark else Track

    var page by remember { mutableStateOf(Page.Overview) }
    var more by remember { mutableStateOf(false) }
    var scan by remember { mutableStateOf<PhoneScan?>(null) }
    var trash by remember { mutableStateOf<List<TrashRec>>(emptyList()) }
    var busy by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var banner by remember { mutableStateOf<String?>(null) }
    var measured by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var trashPick by remember { mutableStateOf(setOf<String>()) }
    var confirmMove by remember { mutableStateOf(false) }
    var confirmEmpty by remember { mutableStateOf(false) }
    var onboarded by remember { mutableStateOf(prefs.getBoolean("onboarded", false)) }
    var step by remember { mutableStateOf(0) }
    var motionMode by remember { mutableStateOf(prefs.getString("motion", "system") ?: "system") }
    var moveBox by remember { mutableStateOf(!systemMotionOff(context) || motionMode == "on") }
    val motion = when (motionMode) {
        "on" -> true
        "off" -> false
        else -> !systemMotionOff(context)
    }
    val scope = rememberCoroutineScope()
    suspend fun refresh() {
        reload(store, { scan = it }, { trash = it }, { busy = it }, { error = it }, { measured = it })
    }
    val askRead = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        scope.launch { refresh() }
    }
    val onboardedNow = rememberUpdatedState(onboarded)

    val life = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(life) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME && onboardedNow.value) scope.launch { refresh() }
        }
        life.addObserver(observer)
        onDispose { life.removeObserver(observer) }
    }
    LaunchedEffect(onboarded) {
        if (onboarded && scan == null) refresh()
    }

    MaterialTheme(colorScheme = scheme) {
        Surface(color = scheme.background, modifier = Modifier.fillMaxSize()) {
            if (!onboarded) {
                Hello(
                    step = step,
                    motion = moveBox,
                    onMotion = { moveBox = it },
                    ink = ink,
                    muted = muted,
                    onNext = {
                        if (step < 2) step += 1 else finishHello(prefs, true, moveBox) { onboarded = true }
                    },
                    onSkip = { finishHello(prefs, false, moveBox) { onboarded = true } },
                )
                return@Surface
            }

            BackHandler(enabled = more || confirmMove || confirmEmpty || page != Page.Overview) {
                when {
                    confirmMove -> confirmMove = false
                    confirmEmpty -> confirmEmpty = false
                    more -> more = false
                    else -> page = Page.Overview
                }
            }

            Column(Modifier.fillMaxSize().statusBarsPadding()) {
                Header(page, ink, muted, motion)
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    when {
                        error != null && scan == null -> Notice(error ?: "Storage could not be read.", "Try again", ink, muted) { scope.launch { refresh() } }
                        scan == null -> Notice("Reading storage", null, ink, muted, null)
                        else -> PageBody(
                            page = page,
                            scan = scan!!,
                            trash = trash,
                            measured = measured,
                            busy = busy,
                            selected = selected,
                            trashPick = trashPick,
                            ink = ink,
                            muted = muted,
                            card = card,
                            accent = accent,
                            track = track,
                            motion = motion,
                            onToggle = { path -> selected = selected.toggle(path) },
                            onTrashToggle = { id -> trashPick = trashPick.toggle(id) },
                            onSelectCopies = {
                                val copies = scan!!.dupes.flatMap { group -> group.files.filter { it.path != group.keepPath }.map { it.path } }
                                selected = copies.toSet()
                            },
                            onAllow = {
                                if (android.os.Build.VERSION.SDK_INT >= 30) openAllFiles(context) else askRead.launch(Manifest.permission.READ_EXTERNAL_STORAGE)
                            },
                            onRefresh = { scope.launch { refresh() } },
                            onEmpty = { confirmEmpty = true },
                            motionMode = motionMode,
                            onMotion = { mode ->
                                motionMode = mode
                                prefs.edit().putString("motion", mode).apply()
                            },
                            canList = store.canListFiles(),
                        )
                    }
                }
                banner?.let { text ->
                    Text(text, color = ink, modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp), fontSize = 13.sp)
                }
                val picking = if (page == Page.Trash) trashPick else selected
                if (page != Page.Settings && page != Page.Overview && picking.isNotEmpty()) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("${picking.size} selected", color = ink, modifier = Modifier.weight(1f))
                        if (page == Page.Trash) {
                            Button(onClick = {
                                scope.launch {
                                    val result = withContext(Dispatchers.IO) { store.restore(trashPick) }
                                    trashPick = emptySet()
                                    banner = resultText("Restored ${result.count}.", result.problems)
                                    refresh()
                                }
                            }) { Text("Restore") }
                        } else {
                            Button(onClick = { confirmMove = true }) { Text("Move to trash") }
                        }
                    }
                }
                BottomNav(page, accent, muted, scheme.background) { chosen ->
                    if (chosen == null) more = true else {
                        page = chosen
                        selected = emptySet()
                    }
                }
            }
        }
    }

    if (more) {
        AlertDialog(
            onDismissRequest = { more = false },
            title = { Text("More") },
            text = {
                Column {
                    TextButton(onClick = { page = Page.Dupes; selected = emptySet(); more = false }) { Text("Duplicates") }
                    TextButton(onClick = { page = Page.Settings; more = false }) { Text("Settings") }
                }
            },
            confirmButton = { TextButton(onClick = { more = false }) { Text("Close") } },
        )
    }
    if (confirmMove) {
        val count = selected.size
        AlertDialog(
            onDismissRequest = { confirmMove = false },
            title = { Text("Move $count to trash?") },
            text = { Text("Luwag copies each file into the app first. If a copy fails, that file stays where it is.") },
            confirmButton = {
                Button(onClick = {
                    confirmMove = false
                    val paths = selected
                    val known = scan?.files?.map { it.path }?.toSet().orEmpty()
                    scope.launch {
                        val result = withContext(Dispatchers.IO) { store.moveToTrash(paths.toList(), known) }
                        selected = emptySet()
                        refresh()
                        banner = resultText("Moved ${result.count} to trash.", result.problems)
                    }
                }) { Text("Move to trash") }
            },
            dismissButton = { TextButton(onClick = { confirmMove = false }) { Text("Cancel") } },
        )
    }
    if (confirmEmpty) {
        AlertDialog(
            onDismissRequest = { confirmEmpty = false },
            title = { Text("Empty trash?") },
            text = { Text("This deletes the copies stored in Luwag. The originals were already removed.") },
            confirmButton = {
                Button(onClick = {
                    confirmEmpty = false
                    scope.launch {
                        withContext(Dispatchers.IO) { store.emptyTrash() }
                        trashPick = emptySet()
                        refresh()
                        banner = "Trash is empty."
                    }
                }) { Text("Empty trash") }
            },
            dismissButton = { TextButton(onClick = { confirmEmpty = false }) { Text("Cancel") } },
        )
    }
}

private suspend fun reload(
    store: PhoneStore,
    setScan: (PhoneScan?) -> Unit,
    setTrash: (List<TrashRec>) -> Unit,
    setBusy: (Boolean) -> Unit,
    setError: (String?) -> Unit,
    setMeasured: (String) -> Unit,
) {
    setBusy(true)
    try {
        val next = withContext(Dispatchers.IO) { store.scan() }
        val bin = withContext(Dispatchers.IO) { store.trash() }
        setScan(next)
        setTrash(bin)
        setError(null)
        setMeasured(SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.US).format(Date()))
    } catch (err: Exception) {
        setError(err.message ?: "Storage could not be read.")
    } finally {
        setBusy(false)
    }
}

private fun finishHello(prefs: android.content.SharedPreferences, saveMotion: Boolean, move: Boolean, done: () -> Unit) {
    val edit = prefs.edit().putBoolean("onboarded", true)
    if (saveMotion) edit.putString("motion", if (move) "on" else "off")
    edit.apply()
    done()
}

private fun systemMotionOff(context: android.content.Context): Boolean {
    val scale = Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f)
    return scale == 0f
}

private fun openAllFiles(context: android.content.Context) {
    val specific = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).apply {
        data = Uri.parse("package:${context.packageName}")
    }
    try {
        context.startActivity(specific)
    } catch (_: Exception) {
        context.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
    }
}

private fun resultText(lead: String, problems: List<String>): String {
    if (problems.isEmpty()) return lead
    return lead + " " + problems.distinct().take(3).joinToString(" ")
}

private fun Set<String>.toggle(value: String): Set<String> =
    if (value in this) this - value else this + value

@Composable
private fun Hello(
    step: Int,
    motion: Boolean,
    onMotion: (Boolean) -> Unit,
    ink: Color,
    muted: Color,
    onNext: () -> Unit,
    onSkip: () -> Unit,
) {
    val titles = listOf("See this phone", "Trash keeps a copy", "The picture can turn")
    val bodies = listOf(
        "Luwag shows free space the system reports. It does not invent sizes.",
        "A file moves only after a copy is stored in the app. Restore puts it back. Empty trash deletes those copies, and the originals are already gone.",
        "You can turn the motion off here, or later in Settings.",
    )
    Column(
        Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(24.dp),
        verticalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Frog(motion, 120.dp, "Luwag frog")
            Spacer(Modifier.height(20.dp))
            Text(titles[step], color = ink, fontSize = 28.sp, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(8.dp))
            Text(bodies[step], color = muted, fontSize = 16.sp)
            if (step == 2) {
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.heightIn(min = 48.dp).clickable { onMotion(!motion) }) {
                    Checkbox(checked = motion, onCheckedChange = onMotion)
                    Text("Let the frog move", color = ink, modifier = Modifier.padding(start = 8.dp))
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onSkip, modifier = Modifier.heightIn(min = 48.dp)) { Text("Skip") }
            Button(onClick = onNext, modifier = Modifier.heightIn(min = 48.dp)) { Text(if (step < 2) "Next" else "Start") }
        }
    }
}

@Composable
private fun Header(page: Page, ink: Color, muted: Color, motion: Boolean) {
    val title = when (page) {
        Page.Overview -> "Overview"
        Page.Large -> "Large files"
        Page.Downloads -> "Old downloads"
        Page.Dupes -> "Duplicates"
        Page.Trash -> "Trash"
        Page.Settings -> "Settings"
    }
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Frog(motion && page == Page.Overview, 40.dp, "Luwag")
        Column(Modifier.padding(start = 12.dp)) {
            Text("Luwag", color = ink, fontWeight = FontWeight.Medium, fontSize = 18.sp)
            Text(title, color = muted, fontSize = 13.sp)
        }
    }
}

@Composable
private fun Frog(moving: Boolean, box: androidx.compose.ui.unit.Dp, description: String) {
    val transition = rememberInfiniteTransition(label = "frog")
    val swing by transition.animateFloat(
        initialValue = -14f,
        targetValue = 14f,
        animationSpec = infiniteRepeatable(tween(4200, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "yaw",
    )
    val yaw = if (moving) swing else 0f
    Image(
        painter = painterResource(R.drawable.ic_frog),
        contentDescription = description,
        contentScale = ContentScale.Fit,
        modifier = Modifier.size(box).graphicsLayer {
            rotationY = yaw
            cameraDistance = 12f * density
        },
    )
}

@Composable
private fun PageBody(
    page: Page,
    scan: PhoneScan,
    trash: List<TrashRec>,
    measured: String,
    busy: Boolean,
    selected: Set<String>,
    trashPick: Set<String>,
    ink: Color,
    muted: Color,
    card: Color,
    accent: Color,
    track: Color,
    motion: Boolean,
    onToggle: (String) -> Unit,
    onTrashToggle: (String) -> Unit,
    onSelectCopies: () -> Unit,
    onAllow: () -> Unit,
    onRefresh: () -> Unit,
    onEmpty: () -> Unit,
    motionMode: String,
    onMotion: (String) -> Unit,
    canList: Boolean,
) {
    when (page) {
        Page.Overview -> Overview(scan, trash.size, measured, busy, ink, muted, card, accent, track, motion, canList, onAllow, onRefresh)
        Page.Large -> FilesPage(scan.listed, scan.large, "No file at 100 MB or larger in the folders Luwag can see.", scan.note, selected, ink, muted, onToggle, onAllow)
        Page.Downloads -> FilesPage(scan.listed, scan.downloads, "No download older than 30 days.", scan.note, selected, ink, muted, onToggle, onAllow)
        Page.Dupes -> DupesPage(scan, selected, ink, muted, onToggle, onSelectCopies, onAllow)
        Page.Trash -> TrashPage(trash, trashPick, ink, muted, onTrashToggle, onEmpty)
        Page.Settings -> SettingsPage(motionMode, canList, ink, muted, onMotion, onAllow)
    }
}

@Composable
private fun Overview(
    scan: PhoneScan,
    trashCount: Int,
    measured: String,
    busy: Boolean,
    ink: Color,
    muted: Color,
    card: Color,
    accent: Color,
    track: Color,
    motion: Boolean,
    canList: Boolean,
    onAllow: () -> Unit,
    onRefresh: () -> Unit,
) {
    LazyColumn(contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 24.dp)) {
        item {
            Column(Modifier.fillMaxWidth()) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                Frog(motion, 112.dp, "Luwag frog")
            }
            if (busy) Text("Reading storage", color = muted, fontSize = 13.sp)
            scan.volumes.forEach { vol ->
                Spacer(Modifier.height(12.dp))
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(card).padding(16.dp)) {
                    Text(vol.label, color = ink, fontWeight = FontWeight.Medium)
                    Text("${fmtBytes(vol.free)} free", color = ink, fontSize = 28.sp, fontWeight = FontWeight.Medium)
                    Text("${fmtBytes(vol.used)} used of ${fmtBytes(vol.total)}", color = muted, fontSize = 14.sp)
                    Spacer(Modifier.height(10.dp))
                    val frac = (vol.used.toFloat() / vol.total.toFloat()).coerceIn(0f, 1f)
                    Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(8.dp)).background(track)) {
                        Box(Modifier.fillMaxWidth(frac).fillMaxHeight().background(accent))
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(vol.path, color = muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (scan.volumes.isEmpty()) {
                Spacer(Modifier.height(12.dp))
                Text("Storage could not be read.", color = ink)
            }
            Spacer(Modifier.height(8.dp))
            Text("Measured $measured", color = muted, fontSize = 12.sp)
            Text("Measured from the system", color = muted, fontSize = 12.sp)
            scan.note?.let { Text(it, color = muted, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp)) }
            if (!canList) {
                Spacer(Modifier.height(12.dp))
                Text("Luwag can measure free space. Listing Downloads, photos, and the other shared folders needs access to all files.", color = ink, fontSize = 14.sp)
                Spacer(Modifier.height(8.dp))
                Button(onClick = onAllow, modifier = Modifier.heightIn(min = 48.dp)) { Text("Allow file lists") }
            } else {
                Spacer(Modifier.height(12.dp))
                Text("Large files: ${scan.large.size}", color = ink)
                Text("Old downloads: ${scan.downloads.size}", color = ink)
                Text("Duplicate groups: ${scan.dupes.size}", color = ink)
                Text("In trash: $trashCount", color = ink)
            }
            Spacer(Modifier.height(12.dp))
            TextButton(onClick = onRefresh, modifier = Modifier.heightIn(min = 48.dp)) { Text("Scan again") }
            }
        }
    }
}

@Composable
private fun FilesPage(
    listed: Boolean,
    files: List<FileRec>,
    empty: String,
    note: String?,
    selected: Set<String>,
    ink: Color,
    muted: Color,
    onToggle: (String) -> Unit,
    onAllow: () -> Unit,
) {
    if (!listed) {
        NeedAccess(ink, muted, onAllow)
        return
    }
    LazyColumn(contentPadding = PaddingValues(bottom = 12.dp)) {
        if (note != null) item { Text(note, color = muted, modifier = Modifier.padding(16.dp), fontSize = 13.sp) }
        if (files.isEmpty()) item { Text(empty, color = muted, modifier = Modifier.padding(16.dp)) }
        items(files, key = { it.path }) { file -> FileRow(file, file.path in selected, ink, muted, null, onToggle) }
    }
}

@Composable
private fun DupesPage(
    scan: PhoneScan,
    selected: Set<String>,
    ink: Color,
    muted: Color,
    onToggle: (String) -> Unit,
    onSelectCopies: () -> Unit,
    onAllow: () -> Unit,
) {
    if (!scan.listed) {
        NeedAccess(ink, muted, onAllow)
        return
    }
    LazyColumn(contentPadding = PaddingValues(bottom = 12.dp)) {
        item {
            Column {
                Text("Same size and the same first and last 64 KB. This is not a full-file check.", color = muted, fontSize = 13.sp, modifier = Modifier.padding(16.dp))
                TextButton(onClick = onSelectCopies, modifier = Modifier.padding(horizontal = 8.dp).heightIn(min = 48.dp)) { Text("Select copies") }
            }
        }
        if (scan.dupes.isEmpty()) item { Text("No matching copies in the scanned folders.", color = muted, modifier = Modifier.padding(16.dp)) }
        scan.dupes.forEach { group ->
            item(key = group.files.joinToString { it.path }) {
                Column(Modifier.padding(top = 8.dp)) {
                    Text("${fmtBytes(group.bytes)}, ${group.files.size} copies", color = ink, fontWeight = FontWeight.Medium, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                    group.files.forEach { file ->
                        val mark = if (file.path == group.keepPath) "Newest" else null
                        FileRow(file, file.path in selected, ink, muted, mark, onToggle)
                    }
                }
            }
        }
    }
}

@Composable
private fun TrashPage(
    trash: List<TrashRec>,
    picked: Set<String>,
    ink: Color,
    muted: Color,
    onToggle: (String) -> Unit,
    onEmpty: () -> Unit,
) {
    LazyColumn(contentPadding = PaddingValues(bottom = 12.dp)) {
        item {
            Column {
                Text("These are copies inside Luwag. Restore writes the file back. Empty trash removes only the copies.", color = muted, fontSize = 13.sp, modifier = Modifier.padding(16.dp))
                if (trash.isNotEmpty()) {
                    TextButton(onClick = onEmpty, modifier = Modifier.padding(horizontal = 8.dp).heightIn(min = 48.dp)) { Text("Empty trash") }
                }
            }
        }
        if (trash.isEmpty()) item { Text("Trash is empty.", color = muted, modifier = Modifier.padding(16.dp)) }
        items(trash, key = { it.id }) { item ->
            Row(
                Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable { onToggle(item.id) }.padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Checkbox(checked = item.id in picked, onCheckedChange = { onToggle(item.id) })
                Column(Modifier.weight(1f).padding(horizontal = 8.dp)) {
                    Text(item.name, color = ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(item.original, color = muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Text(fmtBytes(item.bytes), color = ink, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun SettingsPage(
    motionMode: String,
    canList: Boolean,
    ink: Color,
    muted: Color,
    onMotion: (String) -> Unit,
    onAllow: () -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Motion", color = ink, fontWeight = FontWeight.Medium)
        Text("Off stops the frog. Follow the system uses the phone's animator setting.", color = muted, fontSize = 13.sp)
        Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            MotionChoice("System", motionMode == "system") { onMotion("system") }
            MotionChoice("On", motionMode == "on") { onMotion("on") }
            MotionChoice("Off", motionMode == "off") { onMotion("off") }
        }
        Spacer(Modifier.height(20.dp))
        Text(if (canList) "All-files access is on." else "All-files access is off.", color = ink)
        if (!canList) {
            Spacer(Modifier.height(8.dp))
            Button(onClick = onAllow, modifier = Modifier.heightIn(min = 48.dp)) { Text("Allow file lists") }
        }
        Spacer(Modifier.height(20.dp))
        Text("Version 1.2.0", color = ink)
        Text("Signed with the debug key. Install the APK directly. This is not a Play Store build.", color = muted, fontSize = 13.sp)
    }
}

@Composable
private fun MotionChoice(label: String, on: Boolean, click: () -> Unit) {
    val bg = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface
    val fg = if (on) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onBackground
    Text(
        label,
        color = fg,
        modifier = Modifier
            .heightIn(min = 48.dp)
            .clip(RoundedCornerShape(999.dp))
            .background(bg)
            .clickable(onClick = click)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    )
}

@Composable
private fun NeedAccess(ink: Color, muted: Color, onAllow: () -> Unit) {
    Column(Modifier.padding(16.dp)) {
        Text("File lists need access to shared storage.", color = ink)
        Text("Free space on Overview is already measured.", color = muted, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))
        Spacer(Modifier.height(8.dp))
        Button(onClick = onAllow, modifier = Modifier.heightIn(min = 48.dp)) { Text("Allow file lists") }
    }
}

@Composable
private fun FileRow(file: FileRec, picked: Boolean, ink: Color, muted: Color, mark: String?, onToggle: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable { onToggle(file.path) }.padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = picked, onCheckedChange = { onToggle(file.path) })
        Column(Modifier.weight(1f).padding(horizontal = 8.dp)) {
            Text(file.name, color = ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(file.path, color = muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (mark != null) Text(mark, color = muted, fontSize = 12.sp, modifier = Modifier.padding(end = 8.dp))
        Text(fmtBytes(file.bytes), color = ink, fontSize = 13.sp)
    }
}

@Composable
private fun Notice(text: String, action: String?, ink: Color, muted: Color, onAction: (() -> Unit)?) {
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text(text, color = if (action == null) muted else ink, fontSize = 16.sp)
        if (action != null && onAction != null) {
            Spacer(Modifier.height(12.dp))
            Button(onClick = onAction, modifier = Modifier.heightIn(min = 48.dp)) { Text(action) }
        }
    }
}

@Composable
private fun BottomNav(page: Page, accent: Color, muted: Color, bg: Color, onPick: (Page?) -> Unit) {
    val items = listOf(Page.Overview to "Overview", Page.Large to "Large", Page.Downloads to "Downloads", Page.Trash to "Trash")
    Row(Modifier.fillMaxWidth().background(bg).navigationBarsPadding().heightIn(min = 64.dp)) {
        items.forEach { (target, label) ->
            val on = page == target
            NavItem(label, if (on) accent else muted, Modifier.weight(1f)) { onPick(target) }
        }
        val moreOn = page == Page.Dupes || page == Page.Settings
        NavItem("More", if (moreOn) accent else muted, Modifier.weight(1f)) { onPick(null) }
    }
}

@Composable
private fun NavItem(label: String, color: Color, modifier: Modifier, click: () -> Unit) {
    Box(modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(onClick = click), contentAlignment = Alignment.Center) {
        Text(label, color = color, fontSize = 12.sp, maxLines = 1, fontWeight = FontWeight.Medium)
    }
}
