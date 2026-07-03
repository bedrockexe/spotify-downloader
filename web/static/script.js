const form = document.getElementById("form");
const urlInput = document.getElementById("url");
const goBtn = document.getElementById("go");
const errorBox = document.getElementById("error");

const collection = document.getElementById("collection");
const cover = document.getElementById("cover");
const kicker = document.getElementById("kicker");
const collName = document.getElementById("coll-name");
const collSub = document.getElementById("coll-sub");
const downloadBtn = document.getElementById("download");
const saveLink = document.getElementById("save");
const retryBtn = document.getElementById("retry");
const resetBtn = document.getElementById("reset");
const overall = document.getElementById("overall");
const fill = document.getElementById("fill");
const overallText = document.getElementById("overall-text");
const notice = document.getElementById("notice");

const tracklist = document.getElementById("tracklist");
const trackTpl = document.getElementById("track-tpl");

const STATE_LABEL = {
    queued: "Queued",
    downloading: "Downloading",
    done: "Done",
    failed: "Failed",
};

// --- Session state (drives the reload guard) ---
let jobId = null;
let tracks = [];
let rows = [];
let failedIndexes = [];
let busy = false; // a batch, retry, or single-track download is running
let zipReady = false; // the server has a zip ready to grab
let zipSaved = false; // the user has grabbed the current zip at least once

/* ---------- Small helpers ---------- */
function setLoading(btn, isBusy, busyLabel, idleLabel) {
    btn.disabled = isBusy;
    btn.classList.toggle("loading", isBusy);
    const label = btn.querySelector(".btn-label");
    if (label) label.textContent = isBusy ? busyLabel : idleLabel;
}

function showError(text) {
    errorBox.textContent = text;
    errorBox.classList.remove("hidden");
}
function hideError() {
    errorBox.classList.add("hidden");
}

function toast(text, isError) {
    let el = document.getElementById("toast");
    if (!el) {
        el = document.createElement("div");
        el.id = "toast";
        el.className = "toast";
        document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.toggle("toast-error", !!isError);
    el.classList.add("show");
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.remove("show"), 3600);
}

function fmtDuration(ms) {
    if (!ms) return "";
    const s = Math.round(ms / 1000);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function fmtTotal(ms) {
    const min = Math.round(ms / 60000);
    if (min < 1) return "under a minute";
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60);
    const m = min % 60;
    return `${h} hr${m ? " " + m + " min" : ""}`;
}

function kindFromUrl(url) {
    const m = url.match(/(playlist|album|track)/i);
    return m ? m[1].toLowerCase() : "collection";
}

/* ---------- Rendering ---------- */
function renderCover(list) {
    cover.innerHTML = "";
    const seen = [];
    for (const t of list) {
        if (t.cover_url && !seen.includes(t.cover_url)) seen.push(t.cover_url);
        if (seen.length === 4) break;
    }
    if (seen.length === 0) return;
    if (seen.length >= 4) {
        for (const src of seen.slice(0, 4)) {
            const img = document.createElement("img");
            img.src = src;
            img.alt = "";
            cover.appendChild(img);
        }
    } else {
        const img = document.createElement("img");
        img.className = "solo";
        img.src = seen[0];
        img.alt = "";
        cover.appendChild(img);
    }
}

function renderTracks(list) {
    tracklist.innerHTML = "";
    rows = [];
    list.forEach((t, i) => {
        const node = trackTpl.content.firstElementChild.cloneNode(true);
        node.style.animationDelay = Math.min(i * 16, 500) + "ms";
        node.querySelector(".num").textContent = i + 1;
        const img = node.querySelector(".track-cover img");
        if (t.cover_url) img.src = t.cover_url;
        else img.removeAttribute("src");
        node.querySelector(".track-title").textContent = t.title;
        node.querySelector(".track-artist").textContent = t.artist || "Unknown artist";
        node.querySelector(".track-album").textContent = t.album || "";
        node.querySelector(".track-duration").textContent = fmtDuration(t.duration_ms);
        node.querySelector(".track-state").textContent = STATE_LABEL.queued;
        node.querySelector(".track-dl").addEventListener("click", (e) =>
            downloadOne(i, e.currentTarget)
        );
        tracklist.appendChild(node);
        rows.push(node);
    });
    tracklist.classList.remove("hidden");
}

function setRowStatus(index, status) {
    const row = rows[index];
    if (!row) return;
    row.dataset.status = status;
    row.querySelector(".track-state").textContent = STATE_LABEL[status] || status;
    if (status === "downloading") {
        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
}

function setOverall(current, total) {
    if (!total) {
        fill.classList.add("indeterminate");
        overallText.textContent = "";
        return;
    }
    fill.classList.remove("indeterminate");
    fill.style.width = Math.round((current / total) * 100) + "%";
    overallText.textContent = `${current} / ${total}`;
}

/* ---------- Step 1: preview the track list ---------- */
form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = urlInput.value.trim();
    if (!url) return;

    hideError();
    setLoading(goBtn, true, "Loading…", "Load tracks");

    let res;
    try {
        res = await fetch("/preview", {
            method: "POST",
            body: new URLSearchParams({ url }),
        });
    } catch (err) {
        showError("Couldn't reach the server. Is it still running?");
        setLoading(goBtn, false, "Loading…", "Load tracks");
        return;
    }

    const data = await res.json();
    setLoading(goBtn, false, "Loading…", "Load tracks");
    if (!res.ok) {
        showError(data.error || "Something went wrong.");
        return;
    }

    // Fresh session for this link.
    jobId = data.job_id;
    tracks = data.tracks;
    failedIndexes = [];
    zipReady = false;
    zipSaved = false;
    busy = false;

    // Reset the action row to its initial state.
    saveLink.classList.add("hidden");
    retryBtn.classList.add("hidden");
    resetBtn.classList.add("hidden");
    overall.classList.add("hidden");
    notice.classList.add("hidden");
    fill.style.width = "0";
    downloadBtn.classList.remove("hidden");
    downloadBtn.disabled = false;
    setLoading(downloadBtn, false, "Downloading…", "Download all");

    const totalMs = tracks.reduce((sum, t) => sum + (t.duration_ms || 0), 0);
    const songs = `${data.count} song${data.count === 1 ? "" : "s"}`;
    kicker.textContent = totalMs
        ? `${kindFromUrl(url)} · ${songs} · ${fmtTotal(totalMs)}`
        : `${kindFromUrl(url)} · ${songs}`;
    collName.textContent = data.name;
    collSub.textContent = "Ready to download as tagged .m4a with cover art & lyrics.";

    renderCover(tracks);
    renderTracks(tracks);
    collection.classList.remove("hidden");
    collection.scrollIntoView({ behavior: "smooth", block: "start" });
});

/* ---------- Step 2: download (all, or a retry subset) ---------- */
function setActionsRunning(running) {
    downloadBtn.disabled = running;
    retryBtn.disabled = running;
    resetBtn.disabled = running;
    if (running) {
        saveLink.classList.add("hidden");
        retryBtn.classList.add("hidden");
        resetBtn.classList.add("hidden");
        setLoading(downloadBtn, true, "Downloading…", "Download all");
    } else {
        setLoading(downloadBtn, false, "Downloading…", "Download all");
    }
}

function finishRun(msg) {
    fill.classList.remove("indeterminate");
    fill.style.width = "100%";
    zipReady = true;
    failedIndexes = msg.failed_indexes || [];

    downloadBtn.classList.add("hidden");
    saveLink.href = msg.download;
    saveLink.classList.remove("hidden");
    resetBtn.classList.remove("hidden");

    if (failedIndexes.length) {
        retryBtn.classList.remove("hidden");
        notice.textContent = `${failedIndexes.length} track(s) couldn't be downloaded. Retry them, or grab the rest from the zip (see errors.txt).`;
        notice.classList.remove("hidden");
        collSub.textContent = "Done — with a few skips.";
    } else {
        retryBtn.classList.add("hidden");
        notice.classList.add("hidden");
        collSub.textContent = "All done! Your zip is ready.";
    }
}

async function runJob(indexes) {
    if (!jobId || busy) return;
    busy = true;
    zipSaved = false;
    hideError();
    notice.classList.add("hidden");
    setActionsRunning(true);
    overall.classList.remove("hidden");
    fill.classList.add("indeterminate");
    overallText.textContent = "";

    const targets = indexes || tracks.map((_, i) => i);
    targets.forEach((i) => setRowStatus(i, "queued"));
    collSub.textContent = indexes
        ? "Retrying failed tracks…"
        : "Fetching audio, artwork & lyrics from the web…";

    const body = new URLSearchParams({ job_id: jobId });
    if (indexes) body.set("indexes", indexes.join(","));

    let res;
    try {
        res = await fetch("/start", { method: "POST", body });
    } catch (err) {
        showError("Couldn't reach the server. Is it still running?");
        busy = false;
        setActionsRunning(false);
        return;
    }
    const data = await res.json();
    if (!res.ok) {
        showError(data.error || "Something went wrong.");
        busy = false;
        setActionsRunning(false);
        if (zipReady) {
            // came from a retry — restore the finished-state buttons
            saveLink.classList.remove("hidden");
            resetBtn.classList.remove("hidden");
            if (failedIndexes.length) retryBtn.classList.remove("hidden");
        }
        return;
    }

    const source = new EventSource(`/progress/${data.job_id}`);
    source.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.error) {
            showError(msg.error);
            collSub.textContent = "";
        } else if (msg.done) {
            finishRun(msg);
        } else {
            if (typeof msg.index === "number" && msg.status) {
                setRowStatus(msg.index, msg.status);
            }
            setOverall(msg.current, msg.total);
        }
        if (msg.done) {
            source.close();
            busy = false;
            setActionsRunning(false);
        }
    };
    source.onerror = () => {
        source.close();
        busy = false;
        setActionsRunning(false);
    };
}

downloadBtn.addEventListener("click", () => runJob(null));
retryBtn.addEventListener("click", () => {
    if (failedIndexes.length) runJob(failedIndexes.slice());
});

/* ---------- Per-track download ---------- */
async function downloadOne(index, btn) {
    if (!jobId) return;
    if (busy) {
        toast("Hold on — let the current download finish first.");
        return;
    }
    busy = true;
    btn.classList.add("loading");
    btn.disabled = true;
    try {
        const res = await fetch(`/track/${jobId}/${index}`);
        if (!res.ok) {
            let err = "That track couldn't be downloaded.";
            try {
                err = (await res.json()).error || err;
            } catch (e) {
                /* non-JSON */
            }
            toast(err, true);
            return;
        }
        const blob = await res.blob();
        const t = tracks[index];
        let filename = `${t.title} - ${t.artist}.m4a`;
        const cd = res.headers.get("Content-Disposition");
        if (cd) {
            const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
            if (m) filename = decodeURIComponent(m[1]);
        }
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1500);
        toast(`Saved “${t.title}”.`);
    } catch (err) {
        toast("Couldn't reach the server.", true);
    } finally {
        btn.classList.remove("loading");
        btn.disabled = false;
        busy = false;
    }
}

/* ---------- Grab / re-grab the zip ---------- */
saveLink.addEventListener("click", () => {
    zipSaved = true; // the user has the current zip → relax the reload guard
});

/* ---------- Convert another (reset) ---------- */
resetBtn.addEventListener("click", async () => {
    if (busy) return;
    const old = jobId;
    jobId = null;
    tracks = [];
    rows = [];
    failedIndexes = [];
    zipReady = false;
    zipSaved = false;
    busy = false;

    collection.classList.add("hidden");
    tracklist.classList.add("hidden");
    tracklist.innerHTML = "";
    hideError();
    urlInput.value = "";

    if (old) {
        try {
            await fetch(`/discard/${old}`, { method: "POST" });
        } catch (e) {
            /* best effort */
        }
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
    urlInput.focus();
});

/* ---------- Guard against accidental reloads / tab close ---------- */
window.addEventListener("beforeunload", (event) => {
    if (busy || (zipReady && !zipSaved)) {
        event.preventDefault();
        event.returnValue = ""; // required for the native confirm dialog
        return "";
    }
});
