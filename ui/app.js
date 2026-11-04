/* Luwag window. Every button calls the local engine. Sizes on screen come from that scan. */

const $ = (id) => document.getElementById(id);
const ui = {
  view: 'overview',
  risk: 'all',
  sort: localStorage.getItem('luwag-sort') || 'size',
  query: '',
  sideShut: localStorage.getItem('luwag-side') === 'shut',
  peekShut: localStorage.getItem('luwag-peek') === 'shut',
  sel: new Set(),
  anchor: -1,
  snap: null,
  rev: -1,
  booted: false,
  maximized: false,
  focusId: null,
};

const TITLES = {
  overview: 'Overview',
  junk: 'Junk',
  caches: 'Caches',
  dev: 'Dev leftovers',
  large: 'Large files',
  duplicates: 'Duplicates',
  downloads: 'Old downloads',
  recycle: 'Recycle Bin',
  protected: 'Protected',
};

function fmt(n) {
  n = Number(n) || 0;
  const sign = n < 0 ? '-' : '';
  let value = Math.abs(n);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
  const digits = i === 0 || value >= 100 ? 0 : value >= 10 ? 1 : 2;
  return sign + value.toFixed(digits) + ' ' + units[i];
}

function when(sec) {
  if (!sec) return '';
  try {
    return new Date(sec * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch (e) {
    return '';
  }
}

function mid(path) {
  if (!path || path.length < 72) return path || '';
  return path.slice(0, 30) + '...' + path.slice(-36);
}

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'i');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#' + name);
  svg.append(use);
  return svg;
}

const EXT_MODEL = {
  photo: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'heic', 'tif', 'tiff', 'svg', 'ico', 'raw'],
  film: ['mp4', 'mkv', 'mov', 'avi', 'wmv', 'webm', 'm4v', 'flv'],
  audio: ['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg', 'wma'],
  parcel: ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'iso', 'cab'],
  code: ['js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'py', 'rs', 'go', 'java', 'c', 'cpp', 'h', 'hpp', 'cs', 'json', 'xml', 'html', 'css', 'rb', 'php', 'toml', 'yml', 'yaml', 'lock'],
};

function modelFor(row) {
  const name = String((row && (row.path || row.name || row.label)) || '').toLowerCase();
  const slash = Math.max(name.lastIndexOf('\\'), name.lastIndexOf('/'));
  const base = slash >= 0 ? name.slice(slash + 1) : name;
  const dot = base.lastIndexOf('.');
  const ext = dot > 0 ? base.slice(dot + 1) : '';
  for (const kind of Object.keys(EXT_MODEL)) {
    if (EXT_MODEL[kind].indexOf(ext) >= 0) return kind;
  }
  const group = row && row.group;
  if (group === 'dupes') return 'twins';
  if (group === 'junk' || group === 'recycle') return 'bin';
  if (group === 'caches') return 'cache';
  if (group === 'dev') return 'code';
  if (group === 'downloads') return 'parcel';
  if (group === 'protected') return 'shield';
  const kind = (row && row.kind) || '';
  if (kind === 'aged-tree' || kind === 'all-tree' || kind === 'dir' || kind === 'glob') return 'folder';
  return 'page';
}

function modelImg(name, big) {
  const img = document.createElement('img');
  img.className = big ? 'model peek-model' : 'model';
  img.src = 'models/' + name + '.png';
  img.alt = '';
  return img;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function api() {
  const bridge = window.pywebview && window.pywebview.api;
  if (!bridge || typeof bridge.ready !== 'function') return null;
  return bridge;
}

function say(text) {
  $('live').textContent = text;
}

function toast(text, act) {
  $('toast-text').textContent = text;
  const button = $('toast-act');
  button.hidden = !act;
  button.textContent = act ? act.label : '';
  button.onclick = act ? act.run : null;
  $('toast').hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { $('toast').hidden = true; }, 6000);
  say(text);
}

function motionOn(settings) {
  if (!settings) return !matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (settings.motion === true) return true;
  if (settings.motion === false) return false;
  return !matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function applyChrome(settings) {
  const theme = (settings && settings.theme) || 'system';
  if (theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = theme;
  const on = motionOn(settings);
  document.documentElement.classList.toggle('still', !on);
  if (on) document.documentElement.dataset.motion = 'on';
  else document.documentElement.removeAttribute('data-motion');
}

function paintPanels() {
  const narrowSide = innerWidth < 860;
  const narrowPeek = innerWidth < 1100;
  $('app').classList.toggle('side-shut', ui.sideShut || narrowSide);
  $('app').classList.toggle('peek-shut', ui.peekShut || narrowPeek);
  $('toggle-side').setAttribute('aria-label', (ui.sideShut || narrowSide) ? 'Open the sidebar' : 'Collapse the sidebar');
  $('toggle-peek').setAttribute('aria-label', (ui.peekShut || narrowPeek) ? 'Open the preview' : 'Collapse the preview');
}

function items() {
  const snap = ui.snap;
  if (!snap) return [];
  if (ui.view === 'junk' || ui.view === 'caches' || ui.view === 'dev') {
    const targets = (snap.targets || []).filter((row) => row.group === ui.view);
    const bundles = ui.view === 'dev' ? (snap.bundles || []) : [];
    return targets.concat(bundles);
  }
  if (ui.view === 'large') return (snap.files || []).filter((row) => row.group === 'large');
  if (ui.view === 'downloads') return (snap.files || []).filter((row) => row.group === 'downloads');
  return [];
}

function filtered() {
  const q = ui.query.trim().toLowerCase();
  let rows = items().filter((row) => {
    if (ui.risk !== 'all' && row.risk !== ui.risk) return false;
    if (!q) return true;
    return (row.label || row.name || '').toLowerCase().includes(q) || (row.path || '').toLowerCase().includes(q);
  });
  const sizeOf = (row) => Number(row.eligible != null && row.kind !== 'file' ? row.eligible : row.bytes) || 0;
  rows = rows.slice().sort((a, b) => {
    if (ui.sort === 'name') return (a.label || a.name || '').localeCompare(b.label || b.name || '');
    if (ui.sort === 'old') return (a.mtime || 0) - (b.mtime || 0);
    if (ui.sort === 'new') return (b.mtime || 0) - (a.mtime || 0);
    return sizeOf(b) - sizeOf(a);
  });
  return rows;
}

function findRecord(id) {
  const snap = ui.snap || {};
  const pools = []
    .concat(snap.targets || [], snap.files || [], snap.bundles || []);
  const hit = pools.find((row) => row.id === id);
  if (hit) return hit;
  for (const group of snap.dupes || []) {
    const file = (group.files || []).find((row) => row.id === id);
    if (file) return file;
  }
  return null;
}

function selectedRecords() {
  return [...ui.sel].map(findRecord).filter(Boolean);
}

function bytesOf(row) {
  if (!row) return 0;
  if (row.keep) return Number(row.bytes) || 0;
  if (row.eligible != null && row.group !== 'large' && row.group !== 'downloads' && row.group !== 'dupes') return Number(row.eligible) || 0;
  return Number(row.bytes) || 0;
}

function groupBytes(name) {
  const snap = ui.snap || {};
  return (snap.targets || []).filter((row) => row.group === name && row.status === 'ready')
    .reduce((sum, row) => sum + (Number(row.eligible) || 0), 0);
}

function paintNav() {
  const snap = ui.snap || {};
  const counts = {
    junk: groupBytes('junk'),
    caches: groupBytes('caches'),
    dev: groupBytes('dev') + (snap.bundles || []).reduce((sum, row) => sum + (Number(row.bytes) || 0), 0),
    large: (snap.files || []).filter((row) => row.group === 'large').length,
    duplicates: (snap.dupes || []).length,
    downloads: (snap.files || []).filter((row) => row.group === 'downloads').reduce((sum, row) => sum + (Number(row.bytes) || 0), 0),
    recycle: snap.recycle ? snap.recycle.bytes : 0,
  };
  for (const button of $('nav').querySelectorAll('[data-view]')) {
    button.classList.toggle('on', button.dataset.view === ui.view);
    const em = button.querySelector('em');
    if (!em) continue;
    const value = counts[button.dataset.view];
    if (button.dataset.view === 'large' || button.dataset.view === 'duplicates') em.textContent = value ? String(value) : '';
    else em.textContent = value ? fmt(value) : '';
  }
  const title = $('title');
  if (title.textContent !== TITLES[ui.view]) {
    title.textContent = TITLES[ui.view];
    title.classList.remove('swap');
    void title.offsetWidth;
    title.classList.add('swap');
  }
  const bits = [];
  const rows = filtered();
  if (ui.view === 'overview') {
    const drives = (snap.drives || []);
    if (drives.length) bits.push(fmt(drives.reduce((s, d) => s + d.free, 0)) + ' free');
  } else if (ui.view === 'recycle') {
    if (snap.recycle) bits.push(fmt(snap.recycle.bytes || 0), (snap.recycle.count || 0) + ' items');
  } else if (ui.view === 'duplicates') {
    bits.push((snap.dupes || []).length + ' groups');
  } else if (ui.view !== 'protected') {
    const total = rows.reduce((sum, row) => sum + bytesOf(row), 0);
    bits.push(rows.length + ' shown', fmt(total));
  }
  if (snap.scannedAt) bits.push('Measured ' + snap.scannedAt);
  $('sub').textContent = bits.join('   ');
}

function paintStatus() {
  const snap = ui.snap;
  const bar = $('status');
  if (!snap || !snap.running) {
    bar.hidden = !snap || !snap.partial;
    if (snap && snap.partial) {
      $('status-meter').classList.remove('busy');
      $('status-meter').querySelector('span').style.width = '100%';
      $('status-text').textContent = snap.message || '';
    }
    $('scan').hidden = false;
    $('scan-disk').hidden = false;
    $('stop').hidden = true;
    return;
  }
  bar.hidden = false;
  $('status-meter').classList.add('busy');
  const where = snap.current ? mid(snap.current) : '';
  $('status-text').textContent = (snap.message || 'Working') + (where ? '  ' + where : '');
  $('scan').hidden = true;
  $('scan-disk').hidden = true;
  $('stop').hidden = false;
}

function rowButton(row, max, index) {
  const button = el('button', 'row' + (ui.sel.has(row.id) ? ' sel' : ''));
  button.type = 'button';
  button.dataset.id = row.id;
  button.dataset.index = String(index);
  button.setAttribute('aria-pressed', ui.sel.has(row.id) ? 'true' : 'false');
  const tick = el('span', 'tick');
  tick.append(icon('i-check'));
  const name = el('span', 'name');
  name.append(el('b', '', row.label || row.name || 'Item'));
  const sub = row.path ? mid(row.path) : (row.error || '');
  if (sub) name.append(el('small', '', sub));
  const share = el('span', 'share');
  const fill = el('span');
  const amount = bytesOf(row);
  fill.style.width = max ? Math.max(2, Math.round(amount / max * 100)) + '%' : '0%';
  share.append(fill);
  const size = el('em', '', row.status === 'error' ? 'Error' : fmt(amount));
  button.append(tick, modelImg(modelFor(row)), name, share, size);
  if (row.status === 'error' || amount <= 0) button.disabled = true;
  button.addEventListener('click', (event) => toggle(row.id, index, event));
  button.addEventListener('contextmenu', (event) => openMenu(event, row));
  return button;
}

function paintList(rows, host) {
  const max = rows.reduce((m, row) => Math.max(m, bytesOf(row)), 0);
  const wrap = el('div', 'rows');
  rows.slice(0, 400).forEach((row, index) => wrap.append(rowButton(row, max, index)));
  if (rows.length > 400) wrap.append(el('p', 'note', 'Showing the largest 400 of ' + rows.length + '. Search to narrow this list.'));
  host.append(wrap);
}

function emptyBlock(title, text, buttons) {
  const box = el('div', 'empty');
  box.append(el('h2', '', title), el('p', '', text));
  if (buttons && buttons.length) {
    const line = el('div', 'row-btns');
    for (const spec of buttons) {
      const button = el('button', 'pill' + (spec.primary ? ' primary' : ''), spec.label);
      button.type = 'button';
      button.addEventListener('click', spec.run);
      line.append(button);
    }
    box.append(line);
  }
  return box;
}

function paintOverview(host) {
  const snap = ui.snap || {};
  if (snap.partial) host.append(el('div', 'banner', snap.message || 'Stopped early.'));
  if (!snap.drives || !snap.drives.length) {
    host.append(emptyBlock(
      snap.running ? 'Reading this PC' : 'Nothing measured yet',
      snap.running ? 'Drive totals appear first, then each folder.' : 'Scan this PC to measure drives, temp files, caches, and dev leftovers. Nothing is recycled until you confirm it.',
      snap.running ? [] : [{ label: 'Scan this PC', primary: true, run: () => scan('quick') }],
    ));
    return;
  }
  for (const drive of snap.drives) {
    const used = drive.total ? Math.round(drive.used / drive.total * 100) : 0;
    const block = el('div', 'drive');
    block.append(el('b', '', drive.letter));
    const words = el('div');
    words.append(el('div', '', fmt(drive.used) + ' used, ' + fmt(drive.free) + ' free'));
    words.append(el('small', 'note', 'of ' + fmt(drive.total)));
    const track = el('div', 'meter track');
    track.setAttribute('role', 'meter');
    track.setAttribute('aria-label', drive.letter + ' drive used');
    track.setAttribute('aria-valuemin', '0');
    track.setAttribute('aria-valuemax', '100');
    track.setAttribute('aria-valuenow', String(used));
    const fill = el('span');
    track.append(fill);
    block.append(words, track);
    host.append(block);
    requestAnimationFrame(() => { fill.style.width = used + '%'; });
  }
  host.append(el('p', 'note', 'The bars above are the whole drive. The blocks below are only the folders Luwag measured.'));
  const blocks = [
    ['junk', 'Junk', groupBytes('junk')],
    ['caches', 'Caches', groupBytes('caches')],
    ['dev', 'Dev leftovers', groupBytes('dev') + (snap.bundles || []).reduce((s, r) => s + (Number(r.bytes) || 0), 0)],
    ['downloads', 'Old downloads', (snap.files || []).filter((r) => r.group === 'downloads').reduce((s, r) => s + (Number(r.bytes) || 0), 0)],
  ].filter((row) => row[2] > 0);
  if (blocks.length) {
    const map = el('div', 'map');
    const max = Math.max(...blocks.map((row) => row[2]));
    for (const [view, label, bytes] of blocks) {
      const button = el('button');
      button.type = 'button';
      button.style.flexGrow = String(Math.max(1, Math.round(bytes / max * 8)));
      const marks = { junk: 'bin', caches: 'cache', dev: 'code', downloads: 'parcel' };
      button.append(modelImg(marks[view] || 'page'), el('strong', '', label), el('span', '', fmt(bytes)));
      button.addEventListener('click', () => go(view));
      map.append(button);
    }
    host.append(map);
  }
  const safe = (snap.targets || []).filter((row) => row.risk === 'low' && row.status === 'ready' && row.eligible > 0);
  host.append(el('h2', 'section-label', 'Safe to review'));
  if (!safe.length) {
    host.append(el('p', 'note', snap.running ? 'Still measuring.' : 'No old temp files or rebuildable caches were large enough to list.'));
  } else {
    const line = el('div', 'row-btns');
    const pick = el('button', 'pill', 'Select safe items');
    pick.type = 'button';
    pick.addEventListener('click', () => {
      ui.sel = new Set(safe.map((row) => row.id));
      paint();
      toast('Safe items selected. Nothing is recycled until you confirm.');
    });
    line.append(pick);
    host.append(line);
    paintList(safe, host);
  }
  paintHealth(host, snap);
  paintHistory(host, snap);
  if (snap.settings && snap.settings.motion == null && matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const banner = el('div', 'banner');
    banner.append(el('p', '', 'Motion is off because Windows asked for less motion.'));
    const turn = el('button', 'pill', 'Turn motion on');
    turn.type = 'button';
    turn.addEventListener('click', () => saveSettings({ motion: true }));
    banner.append(turn);
    host.append(banner);
  }
}

function paintHealth(host, snap) {
  host.append(el('h2', 'section-label', 'Disks'));
  const health = snap.health || {};
  if (health.error) {
    host.append(el('p', 'note', health.error));
    return;
  }
  for (const disk of health.disks || []) {
    const line = el('p', '', disk.name + ': ' + disk.status + (disk.size ? ', ' + fmt(disk.size) : ''));
    if (disk.status && disk.status.toLowerCase() !== 'healthy') line.classList.add('warn');
    host.append(line);
  }
  const sense = snap.storageSense;
  const senseLine = el('p', 'note', sense == null ? 'Windows did not share a Storage Sense setting.' : (sense ? 'Storage Sense is on.' : 'Storage Sense is off.'));
  host.append(senseLine);
  const open = el('button', 'pill', 'Open Windows storage settings');
  open.type = 'button';
  open.addEventListener('click', () => api() && api().open_storage());
  host.append(open);
}

function paintHistory(host, snap) {
  const history = snap.history || [];
  host.append(el('h2', 'section-label', 'Free space'));
  if (history.length < 2) {
    const free = (snap.drives || []).reduce((s, d) => s + d.free, 0);
    host.append(el('p', 'note', history.length ? 'Free today: ' + fmt(free) + '. The line appears after a scan on another day.' : 'A scan records free space. The line appears after a second day.'));
    return;
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'history');
  svg.setAttribute('viewBox', '0 0 300 88');
  svg.setAttribute('role', 'img');
  const frees = history.map((p) => Number(p.free) || 0);
  const min = Math.min(...frees);
  const max = Math.max(...frees);
  const span = Math.max(1, max - min);
  const pts = history.map((point, i) => {
    const x = history.length === 1 ? 0 : (i / (history.length - 1)) * 300;
    const y = 80 - ((Number(point.free) - min) / span) * 72;
    return x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  line.setAttribute('points', pts);
  svg.append(line);
  const first = history[0];
  const last = history[history.length - 1];
  svg.setAttribute('aria-label', 'Free space from ' + first.t + ' (' + fmt(first.free) + ') to ' + last.t + ' (' + fmt(last.free) + ')');
  host.append(svg);
}

function paintDupes(host) {
  const groups = ui.snap.dupes || [];
  if (!groups.length) {
    host.append(emptyBlock(
      'No duplicate groups yet',
      'Duplicates are checked in Desktop, Documents, Downloads, Pictures, Videos, and Music. A group shares a size and the same first and last 64 KB. Scan folders to look.',
      [{ label: 'Scan folders', primary: true, run: () => scan('disk') }],
    ));
    return;
  }
  if (ui.snap.truncated && ui.snap.truncated.dupes) {
    host.append(el('p', 'note', 'The list stopped early so the scan would finish. It is not every duplicate on the PC.'));
  }
  for (const group of groups) {
    const block = el('section', 'dupe');
    const title = group.match === 'full' ? 'Full file match' : group.match === 'different' ? 'Sample matched, full file did not' : 'Same size and sample';
    block.append(el('h3', '', group.files.length + ' files, ' + fmt(group.bytes) + ' each. ' + title));
    const copies = el('button', 'pill', 'Check the whole file');
    copies.type = 'button';
    copies.addEventListener('click', () => confirmDupe(group.id));
    block.append(copies);
    for (const file of group.files) {
      const button = rowButton(file, group.bytes, 0);
      if (file.keep) button.querySelector('.name').append(el('small', 'keep', 'Newest, kept unless you select it'));
      block.append(button);
    }
    host.append(block);
  }
}

function paintRecycle(host) {
  const bin = (ui.snap && ui.snap.recycle) || { bytes: 0, count: 0, error: '' };
  if (bin.error) host.append(el('p', 'warn', bin.error));
  host.append(el('h2', '', fmt(bin.bytes || 0)));
  host.append(el('p', 'note', (bin.count || 0) + ' items are in the Recycle Bin. Emptying it removes them for good. Recycling from Luwag does not empty the bin.'));
  const line = el('div', 'row-btns');
  const show = el('button', 'pill', 'Show the bin');
  show.type = 'button';
  show.addEventListener('click', () => api() && api().open_bin());
  const empty = el('button', 'pill bad', 'Empty Recycle Bin');
  empty.type = 'button';
  empty.disabled = !(bin.count > 0);
  empty.addEventListener('click', confirmEmpty);
  line.append(show, empty);
  host.append(line);
}

function paintProtected(host) {
  const rows = (ui.snap && ui.snap.protected) || [];
  host.append(el('p', 'note', 'These paths cannot be recycled. Personal folders can, but only after you type RECYCLE.'));
  const list = el('div', 'rows');
  for (const row of rows) {
    const line = el('div', 'row');
    line.append(icon('i-shield'));
    const name = el('span', 'name');
    name.append(el('b', '', row.path), el('small', '', row.why));
    line.append(name);
    if (row.removable) {
      const button = el('button', 'pill', 'Remove');
      button.type = 'button';
      button.addEventListener('click', async () => {
        await api().unprotect(row.path);
        ui.snap = await api().poll();
        paint();
      });
      line.append(button);
    }
    list.append(line);
  }
  host.append(list);
}

function paintBody() {
  const host = $('body');
  host.replaceChildren();
  const snap = ui.snap;
  if (!snap) {
    host.append(emptyBlock('Luwag is not connected', 'Open Luwag from Luwag.bat so it can read this PC.', []));
    return;
  }
  const listViews = ['junk', 'caches', 'dev', 'large', 'downloads'];
  $('risks').hidden = !listViews.includes(ui.view) && ui.view !== 'duplicates';
  $('sort').hidden = ui.view === 'overview' || ui.view === 'recycle' || ui.view === 'protected';
  if (ui.view === 'overview') return paintOverview(host);
  if (ui.view === 'duplicates') return paintDupes(host);
  if (ui.view === 'recycle') return paintRecycle(host);
  if (ui.view === 'protected') return paintProtected(host);
  const rows = filtered();
  if (snap.running && !rows.length) {
    host.append(emptyBlock('Measuring', snap.message || 'Reading folders.', []));
    return;
  }
  if (!rows.length) {
    const disk = ui.view === 'large';
    host.append(emptyBlock(
      disk ? 'No large files in the list' : 'Nothing in this list',
      disk
        ? 'Large files outside Windows folders show up after Scan folders. The quick scan only measures known temp and cache folders.'
        : 'This list is empty for the current search and filter.',
      disk ? [{ label: 'Scan folders', primary: true, run: () => scan('disk') }] : [{ label: 'Scan this PC', primary: true, run: () => scan('quick') }],
    ));
    return;
  }
  if (ui.view === 'downloads' && snap.truncated && snap.truncated.downloads) {
    host.append(el('p', 'note', 'Showing the first 800 old downloads, not every file.'));
  }
  paintList(rows, host);
  if ((snap.errors || []).length && ui.view === 'junk') {
    host.append(el('h2', 'section-label', 'Folders that could not be read'));
    for (const err of snap.errors.slice(0, 8)) host.append(el('p', 'note', mid(err.path) + ' ' + err.message));
  }
}

function paintPeek() {
  const host = $('peek-body');
  const rail = $('peek-rail');
  host.replaceChildren();
  rail.replaceChildren();
  const chosen = selectedRecords();
  $('peek-label').textContent = chosen.length === 1 ? (chosen[0].label || chosen[0].name) : chosen.length ? chosen.length + ' selected' : 'Details';
  if (chosen.length === 1) paintOne(host, chosen[0]);
  else if (chosen.length > 1) paintMany(host, chosen);
  else paintViewHelp(host);
  const railBtn = el('button', 'icon');
  railBtn.type = 'button';
  railBtn.append(icon('i-refresh'));
  railBtn.setAttribute('aria-label', 'Scan this PC');
  railBtn.addEventListener('click', () => scan('quick'));
  rail.append(railBtn);
}

function fact(list, term, value) {
  list.append(el('dt', '', term), el('dd', '', value));
}

function paintOne(host, row) {
  host.append(modelImg(modelFor(row), true));
  host.append(el('h2', 'pname', row.label || row.name || 'Item'));
  const facts = el('dl', 'facts');
  fact(facts, 'Size', fmt(bytesOf(row)));
  fact(facts, 'Risk', row.risk === 'low' ? 'Safe' : 'Review');
  if (row.mtime) fact(facts, 'Changed', when(row.mtime));
  if (row.path) fact(facts, 'Path', row.path);
  if (row.why) fact(facts, 'Why it is here', row.why);
  if (row.keep) fact(facts, 'Duplicate', 'This is the newest copy.');
  host.append(facts);
  const acts = el('div', 'acts');
  acts.append(action('Recycle', 'i-trash', true, () => confirmRecycle([...ui.sel])));
  if (row.path) {
    acts.append(action('Show in Explorer', 'i-open', false, () => api().reveal(row.path)));
    acts.append(action('Copy path', 'i-copy', false, () => copyText(row.path)));
    acts.append(action('Protect', 'i-lock', false, () => protectPaths([row.path])));
  }
  host.append(acts);
}

function paintMany(host, rows) {
  const bytes = rows.reduce((sum, row) => sum + bytesOf(row), 0);
  host.append(el('h2', 'pname', rows.length + ' selected'));
  host.append(el('p', 'note', fmt(bytes) + ' in this selection. Recycling sends them to the Recycle Bin.'));
  const acts = el('div', 'acts');
  acts.append(action('Recycle', 'i-trash', true, () => confirmRecycle([...ui.sel])));
  acts.append(action('Copy paths', 'i-copy', false, () => copyText(rows.map((row) => row.path).filter(Boolean).join('\n'))));
  host.append(acts);
}

function paintViewHelp(host) {
  const copy = {
    overview: ['Overview', 'Drive totals are the whole disk. Folder lists are only what Luwag measured. Safe items still wait for a confirm.'],
    junk: ['Junk', 'Temp files older than your setting, plus crash dumps and thumbnail caches. Temp files from the last few days stay.'],
    caches: ['Caches', 'Browser and editor caches. Recycling them does not sign you out. Pages and the editor rebuild them.'],
    dev: ['Dev leftovers', 'Caches and logs from Claude, Codex, Grok, npm, pip, and project folders such as node_modules. Skills, settings, and source are not in the safe list.'],
    large: ['Large files', 'Files over your size setting, outside Windows, Program Files, and ProgramData. Personal folders need the word RECYCLE.'],
    duplicates: ['Duplicates', 'Same size and the same first and last 64 KB. Use Check the whole file before trusting a group. The newest copy stays unselected.'],
    downloads: ['Old downloads', 'Files in Downloads older than your setting. They are yours, so they are marked Review.'],
    recycle: ['Recycle Bin', 'Items Luwag recycled can be restored from Windows until you empty the bin. Emptying is permanent.'],
    protected: ['Protected', 'Windows, sign-in files, Git history, and folders you add. Luwag refuses these even if a selection includes them.'],
  };
  const [title, text] = copy[ui.view] || copy.overview;
  const viewModel = {
    overview: 'disk', junk: 'bin', caches: 'cache', dev: 'code', large: 'page',
    duplicates: 'twins', downloads: 'parcel', recycle: 'bin', protected: 'shield',
  };
  host.append(modelImg(viewModel[ui.view] || 'page', true));
  host.append(el('h2', 'pname', title), el('p', 'note', text));
  const keys = el('details', 'keys');
  const summary = el('summary', '', 'Keyboard');
  keys.append(summary);
  const list = document.createElement('dl');
  const pairs = [['F5', 'Scan this PC'], ['Ctrl F', 'Search'], ['Delete', 'Recycle the selection'], ['Ctrl A', 'Select visible'], ['Esc', 'Clear the selection'], ['[', 'Sidebar'], [']', 'Preview']];
  for (const [key, label] of pairs) {
    list.append(el('dt', '', key), el('dd', '', label));
  }
  keys.append(list);
  host.append(keys);
}

function action(label, glyph, bad, run) {
  const button = el('button', 'act' + (bad ? ' bad' : ''));
  button.type = 'button';
  button.append(icon(glyph), el('span', '', label));
  button.addEventListener('click', run);
  return button;
}

function paintSel() {
  const rows = selectedRecords();
  const bar = $('selbar');
  bar.hidden = rows.length === 0;
  document.body.classList.toggle('has-bar', rows.length > 0);
  if (!rows.length) return;
  const bytes = rows.reduce((sum, row) => sum + bytesOf(row), 0);
  $('sel-count').textContent = rows.length + ' selected, ' + fmt(bytes);
}

function paint() {
  paintNav();
  paintStatus();
  paintBody();
  paintPeek();
  paintSel();
}

function go(view) {
  ui.view = view;
  ui.anchor = -1;
  paint();
}

function toggle(id, index, event) {
  if (event && event.shiftKey && ui.anchor >= 0) {
    const rows = filtered();
    const start = Math.min(ui.anchor, index);
    const end = Math.max(ui.anchor, index);
    for (let i = start; i <= end && i < rows.length; i += 1) ui.sel.add(rows[i].id);
  } else if (ui.sel.has(id) && !(event && event.shiftKey)) ui.sel.delete(id);
  else ui.sel.add(id);
  ui.anchor = index;
  ui.focusId = id;
  paint();
}

async function scan(mode) {
  if (!api()) return toast('Open Luwag from Luwag.bat so it can read this PC.');
  const result = await api().scan(mode);
  if (!result.ok) return toast(result.error || 'The scan did not start.');
  say(mode === 'disk' ? 'Scanning folders.' : 'Scanning this PC.');
  poll();
}

async function poll() {
  if (!api()) return;
  const snap = await api().poll();
  const changed = !ui.snap || snap.rev !== ui.rev;
  ui.snap = snap;
  ui.rev = snap.rev;
  applyChrome(snap.settings);
  if (changed) paint();
  else paintStatus();
  if (snap.running) setTimeout(poll, 300);
  else if (changed) say(snap.message || 'Scan finished.');
}

async function saveSettings(patch) {
  if (!api()) return;
  const result = await api().save_settings(patch);
  if (!result.ok) return toast(result.error || 'Settings were not saved.');
  ui.snap.settings = result.settings;
  applyChrome(result.settings);
  paint();
}

function openMenu(event, row) {
  event.preventDefault();
  const menu = $('menu');
  menu.replaceChildren();
  const add = (label, bad, run) => {
    const button = el('button', bad ? 'bad' : '', label);
    button.type = 'button';
    button.role = 'menuitem';
    button.addEventListener('click', () => { menu.hidden = true; run(); });
    menu.append(button);
  };
  if (!ui.sel.has(row.id)) ui.sel.add(row.id);
  add('Recycle', true, () => confirmRecycle([...ui.sel]));
  if (row.path) add('Show in Explorer', false, () => api().reveal(row.path));
  if (row.path) add('Copy path', false, () => copyText(row.path));
  if (row.path) add('Protect', false, () => protectPaths([row.path]));
  menu.hidden = false;
  menu.style.left = Math.min(event.clientX, innerWidth - 220) + 'px';
  menu.style.top = Math.min(event.clientY, innerHeight - 160) + 'px';
  menu.querySelector('button').focus();
}

async function copyText(text) {
  if (api()) await api().copy_text(text);
  else if (navigator.clipboard) await navigator.clipboard.writeText(text);
  toast('Copied.');
}

async function protectPaths(paths) {
  for (const path of paths) {
    const result = await api().protect(path);
    if (!result.ok) return toast(result.error || 'That path was not protected.');
  }
  ui.sel.clear();
  ui.snap = await api().poll();
  paint();
  toast('Protected. The next scan skips it, and Recycle will refuse it.');
}

function confirmRecycle(ids) {
  if (!ids.length) return;
  showSheet(async (body) => {
    body.append(el('h2', '', 'Checking the selection'), el('p', '', 'Nothing is recycled yet.'));
    const plan = await api().prepare(ids);
    body.replaceChildren();
    if (!plan.ok) {
      body.append(el('h2', '', 'Not recycled'));
      body.append(el('p', '', plan.error || 'That selection cannot be recycled.'));
      const close = el('button', 'pill', 'Close');
      close.type = 'button';
      close.addEventListener('click', () => $('sheet').close());
      body.append(close);
      return;
    }
    const form = document.createElement('form');
    form.method = 'dialog';
    form.append(el('h2', '', 'Recycle ' + plan.count + ' items'));
    form.append(el('p', '', 'They go to the Recycle Bin. You can restore them from there until the bin is emptied. About ' + fmt(plan.bytes) + '.'));
    const list = el('div', 'list');
    for (const name of plan.names || []) list.append(el('div', 'line', name));
    if (plan.more) list.append(el('p', 'note', 'And ' + plan.more + ' more.'));
    form.append(list);
    let field = null;
    if (plan.needsWord) {
      field = el('div', 'field');
      const label = el('label', '', 'Type RECYCLE to confirm');
      label.htmlFor = 'word';
      const input = el('input');
      input.id = 'word';
      input.type = 'text';
      input.autocomplete = 'off';
      input.spellcheck = false;
      field.append(label, input, el('p', '', 'This selection is large, or it includes a personal folder, a download, a cache, or a duplicate.'));
      form.append(field);
    }
    const btns = el('div', 'btns');
    const cancel = el('button', 'pill', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', () => $('sheet').close());
    const go = el('button', 'pill bad', 'Recycle');
    go.type = 'submit';
    btns.append(cancel, go);
    form.append(btns);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const word = field ? field.querySelector('input').value.trim() : '';
      go.disabled = true;
      const result = await api().recycle(ids, word);
      go.disabled = false;
      if (!result.ok && !result.recycled) {
        const prior = form.querySelector('.warn');
        if (prior) prior.remove();
        form.append(el('p', 'warn', result.error || 'Nothing was recycled.'));
        return;
      }
      $('sheet').close();
      ui.sel.clear();
      const failed = result.failedCount ? ' ' + result.failedCount + ' could not be moved.' : '';
      toast('Recycled ' + result.recycled + ' items.' + failed, { label: 'Scan again', run: () => scan('quick') });
      ui.snap = await api().poll();
      paint();
    });
    body.append(form);
    (field ? field.querySelector('input') : cancel).focus();
  });
}

function confirmEmpty() {
  showSheet((body) => {
    const form = document.createElement('form');
    form.method = 'dialog';
    form.append(el('h2', '', 'Empty the Recycle Bin'));
    form.append(el('p', '', 'This removes everything in the bin, including files Luwag did not put there. It cannot be undone from Luwag.'));
    const field = el('div', 'field');
    const label = el('label', '', 'Type EMPTY to confirm');
    label.htmlFor = 'empty-word';
    const input = el('input');
    input.id = 'empty-word';
    input.type = 'text';
    input.autocomplete = 'off';
    field.append(label, input);
    form.append(field);
    const btns = el('div', 'btns');
    const cancel = el('button', 'pill', 'Cancel');
    cancel.type = 'button';
    cancel.addEventListener('click', () => $('sheet').close());
    const go = el('button', 'pill bad', 'Empty Recycle Bin');
    go.type = 'submit';
    btns.append(cancel, go);
    form.append(btns);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const result = await api().empty_bin(input.value.trim());
      if (!result.ok) {
        const prior = form.querySelector('.warn');
        if (prior) prior.remove();
        form.append(el('p', 'warn', result.error || 'The bin was not emptied.'));
        return;
      }
      $('sheet').close();
      ui.snap = await api().poll();
      paint();
      toast('The Recycle Bin was emptied.');
    });
    body.append(form);
    input.focus();
  });
}

function showSheet(fill) {
  const sheet = $('sheet');
  sheet.replaceChildren();
  const body = el('div', 'sheet-pad');
  sheet.append(body);
  if (!sheet.open) sheet.showModal();
  fill(body);
}

function openSettings() {
  const snap = ui.snap || { settings: {} };
  const settings = snap.settings || {};
  const host = $('prefs-body');
  host.replaceChildren();
  const theme = el('div', 'field');
  theme.append(el('span', '', 'Theme'));
  const seg = el('div', 'seg');
  for (const [value, label] of [['system', 'Match Windows'], ['light', 'Light'], ['dark', 'Dark']]) {
    const button = el('button', 'pill' + ((settings.theme || 'system') === value ? ' on' : ''), label);
    button.type = 'button';
    button.addEventListener('click', () => saveSettings({ theme: value }).then(openSettings));
    seg.append(button);
  }
  theme.append(seg);
  const motion = el('div', 'field');
  motion.append(el('span', '', 'Motion'));
  const motionSeg = el('div', 'seg');
  const current = settings.motion == null ? 'system' : settings.motion ? 'on' : 'off';
  for (const [value, label] of [['system', 'Match Windows'], ['on', 'On'], ['off', 'Off']]) {
    const button = el('button', 'pill' + (current === value ? ' on' : ''), label);
    button.type = 'button';
    button.addEventListener('click', () => {
      const motionValue = value === 'system' ? null : value === 'on';
      saveSettings({ motion: motionValue }).then(openSettings);
    });
    motionSeg.append(button);
  }
  motion.append(motionSeg, el('p', '', 'Match Windows turns motion off when Windows asks for less motion.'));
  const limits = document.createElement('form');
  limits.className = 'field';
  limits.append(el('span', '', 'Limits, used on the next scan'));
  const large = numberField('large-min', 'Large file minimum, MB', settings.largeMinMB || 100, 10, 10000);
  const days = numberField('dl-days', 'Downloads older than, days', settings.downloadDays || 30, 1, 3650);
  const temp = numberField('temp-days', 'Temp files older than, days', settings.tempDays || 7, 1, 3650);
  const save = el('button', 'pill primary', 'Save limits');
  save.type = 'submit';
  limits.append(large.wrap, days.wrap, temp.wrap, save);
  limits.addEventListener('submit', (event) => {
    event.preventDefault();
    saveSettings({
      largeMinMB: Number(large.input.value),
      downloadDays: Number(days.input.value),
      tempDays: Number(temp.input.value),
    });
    toast('Limits saved. They apply on the next scan.');
  });
  const protect = document.createElement('form');
  protect.className = 'field';
  protect.append(el('span', '', 'Protect a folder'));
  const pathLabel = el('label', '', 'Folder path');
  pathLabel.htmlFor = 'protect-path';
  const pathInput = el('input');
  pathInput.id = 'protect-path';
  pathInput.type = 'text';
  pathInput.spellcheck = false;
  const add = el('button', 'pill', 'Protect path');
  add.type = 'submit';
  protect.append(pathLabel, pathInput, el('p', '', 'Luwag will refuse to recycle this path.'), add);
  protect.addEventListener('submit', async (event) => {
    event.preventDefault();
    const result = await api().protect(pathInput.value.trim());
    if (!result.ok) return toast(result.error || 'That path was not protected.');
    ui.snap = await api().poll();
    toast('Protected.');
    openSettings();
  });
  const extras = el('div', 'list');
  for (const path of settings.extraProtected || []) {
    const line = el('div', 'line');
    line.append(el('span', '', path));
    const remove = el('button', '', 'Remove');
    remove.type = 'button';
    remove.addEventListener('click', async () => {
      await api().unprotect(path);
      ui.snap = await api().poll();
      openSettings();
    });
    line.append(remove);
    extras.append(line);
  }
  const tools = el('div', 'btns');
  const exp = el('button', 'pill', 'Export CSV');
  exp.type = 'button';
  exp.addEventListener('click', async () => {
    const result = await api().export_csv();
    if (result.ok) toast('Saved ' + result.rows + ' rows.', { label: 'Show file', run: () => api().reveal(result.path) });
  });
  const summary = el('button', 'pill', 'Copy summary');
  summary.type = 'button';
  summary.addEventListener('click', async () => {
    const result = await api().summary();
    await copyText(result.text || '');
  });
  tools.append(exp, summary);
  host.append(theme, motion, limits, protect, extras, tools);
  if (!$('prefs').open) $('prefs').showModal();
}

function numberField(id, label, value, min, max) {
  const wrap = el('div', 'field');
  const lab = el('label', '', label);
  lab.htmlFor = id;
  const input = el('input');
  input.id = id;
  input.type = 'number';
  input.min = String(min);
  input.max = String(max);
  input.value = String(value);
  wrap.append(lab, input);
  return { wrap, input };
}

async function confirmDupe(id) {
  toast('Checking every byte.');
  const result = await api().confirm_dupe(id);
  ui.snap = await api().poll();
  paint();
  if (!result.ok) toast(result.error || 'The check did not finish.');
  else toast(result.match === 'full' ? 'Those files match byte for byte.' : 'The full files do not match.');
}

function selectVisible() {
  for (const row of filtered()) if (bytesOf(row) > 0) ui.sel.add(row.id);
  for (const group of (ui.view === 'duplicates' ? (ui.snap.dupes || []) : [])) {
    for (const file of group.files) if (!file.keep) ui.sel.add(file.id);
  }
  paint();
}

function onKey(event) {
  const tag = document.activeElement && document.activeElement.tagName;
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  if (event.key === 'Escape') {
    if ($('menu') && !$('menu').hidden) { $('menu').hidden = true; return; }
    if ($('sheet').open || $('prefs').open) return;
    ui.sel.clear();
    paint();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
    event.preventDefault();
    $('query').focus();
    return;
  }
  if (typing) return;
  if (event.key === 'F5') { event.preventDefault(); scan('quick'); }
  else if (event.key === '[') { ui.sideShut = !ui.sideShut; localStorage.setItem('luwag-side', ui.sideShut ? 'shut' : 'open'); paintPanels(); }
  else if (event.key === ']') { ui.peekShut = !ui.peekShut; localStorage.setItem('luwag-peek', ui.peekShut ? 'shut' : 'open'); paintPanels(); }
  else if (event.key === 'Delete' && ui.sel.size) { event.preventDefault(); confirmRecycle([...ui.sel]); }
  else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && ui.view !== 'overview') {
    event.preventDefault();
    selectVisible();
  }
}

async function setMaxIcon() {
  if (!api()) return;
  const state = await api().window_state();
  ui.maximized = !!state.maximized;
  $('w-max').querySelector('use').setAttribute('href', ui.maximized ? '#i-unmax' : '#i-max');
  $('w-max').setAttribute('aria-label', ui.maximized ? 'Restore' : 'Maximize');
  $('grips').hidden = ui.maximized;
}

async function boot() {
  if (ui.booted || !api()) return;
  ui.booted = true;
  try {
    ui.snap = await api().ready();
    ui.rev = ui.snap.rev;
    applyChrome(ui.snap.settings);
    $('sort').value = ui.sort;
    paintPanels();
    paint();
    await scan('quick');
    setMaxIcon();
  } catch (err) {
    ui.booted = false;
    const host = $('body');
    host.replaceChildren();
    host.append(emptyBlock('Luwag could not start the scan', (err && err.message) || 'The window lost the scanner.', [
      { label: 'Try again', primary: true, run: () => boot() },
    ]));
  }
}

window.addEventListener('pywebviewready', () => setTimeout(boot, 0));
(function connect(left) {
  if (ui.booted) return;
  if (api()) { setTimeout(boot, 0); return; }
  if (left <= 0) { paint(); return; }
  setTimeout(() => connect(left - 1), 100);
})(80);
window.addEventListener('resize', () => { paintPanels(); setMaxIcon(); });
$('toggle-side').addEventListener('click', () => {
  ui.sideShut = !ui.sideShut;
  localStorage.setItem('luwag-side', ui.sideShut ? 'shut' : 'open');
  paintPanels();
});
$('toggle-peek').addEventListener('click', () => {
  ui.peekShut = !ui.peekShut;
  localStorage.setItem('luwag-peek', ui.peekShut ? 'shut' : 'open');
  paintPanels();
});
$('nav').addEventListener('click', (event) => {
  const button = event.target.closest('[data-view]');
  if (button) go(button.dataset.view);
});
$('query').addEventListener('input', () => { ui.query = $('query').value; paint(); });
$('sort').addEventListener('change', () => {
  ui.sort = $('sort').value;
  localStorage.setItem('luwag-sort', ui.sort);
  paint();
});
for (const button of $('risks').querySelectorAll('button')) {
  button.addEventListener('click', () => {
    ui.risk = button.dataset.risk;
    for (const other of $('risks').querySelectorAll('button')) other.classList.toggle('on', other === button);
    paint();
  });
}
$('scan').addEventListener('click', () => scan('quick'));
$('scan-disk').addEventListener('click', () => scan('disk'));
$('stop').addEventListener('click', () => api() && api().cancel());
$('open-settings').addEventListener('click', openSettings);
$('prefs-close').addEventListener('click', () => $('prefs').close());
$('sel-recycle').addEventListener('click', () => confirmRecycle([...ui.sel]));
$('sel-reveal').addEventListener('click', () => {
  const row = selectedRecords().find((item) => item.path);
  if (row) api().reveal(row.path);
});
$('sel-copy').addEventListener('click', () => copyText(selectedRecords().map((row) => row.path).filter(Boolean).join('\n')));
$('sel-protect').addEventListener('click', () => protectPaths(selectedRecords().map((row) => row.path).filter(Boolean)));
$('sel-all').addEventListener('click', selectVisible);
$('sel-none').addEventListener('click', () => { ui.sel.clear(); paint(); });
$('w-min').addEventListener('click', () => api() && api().minimize());
$('w-max').addEventListener('click', async () => { if (api()) { await api().toggle_maximize(); setMaxIcon(); } });
$('w-close').addEventListener('click', () => api() && api().close());
for (const grip of $('grips').children) {
  grip.addEventListener('mousedown', (event) => {
    if (event.button !== 0 || !api()) return;
    event.preventDefault();
    api().start_resize(grip.dataset.edge);
  });
}
document.addEventListener('dblclick', (event) => {
  if (event.target.closest('.pywebview-drag-region') && api()) api().toggle_maximize().then(setMaxIcon);
});
document.addEventListener('keydown', onKey);
document.addEventListener('click', (event) => {
  if (!event.target.closest('#menu')) $('menu').hidden = true;
});
$('sheet').addEventListener('cancel', () => {});
