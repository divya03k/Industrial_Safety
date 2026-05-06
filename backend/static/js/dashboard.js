// ✅ showPage, showProcessedFrame, showProcessedVideo, updateViolationStats,
//    updateAlertCount are all defined in index.html — do NOT redefine here.

let analyticsChart       = null
let analyticsData        = null
let lastAlertMessage     = null
let stream               = null
let detectionInterval    = null
let audioUnlocked        = false
let frameCount           = 0
let lastFpsTime          = Date.now()
let totalFramesProcessed = 0
let totalDetections      = 0

// ── Unlock audio on first user interaction ──────────────────────────────
document.addEventListener("click", () => {
  if (!audioUnlocked) {
    let sound = document.getElementById("alertSound")
    if (sound) {
      sound.play()
        .then(() => { sound.pause(); sound.currentTime = 0; audioUnlocked = true; })
        .catch(() => {})
    }
  }
})

// ── Safe fetch helper — always returns parsed JSON or null ───────────────
async function safeFetch(url, options) {
  try {
    const res = await fetch(url, options)
    const text = await res.text()
    try {
      return { ok: res.ok, status: res.status, data: JSON.parse(text) }
    } catch (e) {
      // Server returned HTML (e.g. Flask error page) instead of JSON
      console.error(`[safeFetch] ${url} returned non-JSON (status ${res.status}):`, text.slice(0, 300))
      return { ok: false, status: res.status, data: null, raw: text }
    }
  } catch (e) {
    console.error(`[safeFetch] Network error for ${url}:`, e)
    return { ok: false, status: 0, data: null }
  }
}

/* ============================================================
   CAMERA
============================================================ */
async function startCamera() {
  const video = document.getElementById("webcam")
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: true })
    video.srcObject = stream
    video.onloadedmetadata = () => {
      video.play()
      document.getElementById("camStatus").innerText            = "Live"
      document.getElementById("liveStatus").innerText           = "Live"
      document.getElementById("liveDot").style.display          = "inline-block"
      document.getElementById("detectionOverlay").style.display = "block"
      startDetection()
    }
  } catch (err) {
    console.error("Camera error:", err)
    document.getElementById("camStatus").innerText = "Error: " + err.message
  }
}

function stopCamera() {
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  clearInterval(detectionInterval); detectionInterval = null
  document.getElementById("camStatus").innerText            = "Idle"
  document.getElementById("liveStatus").innerText           = "Idle"
  document.getElementById("liveDot").style.display          = "none"
  document.getElementById("detectionOverlay").style.display = "none"
  document.getElementById("fpsDisplay").innerText           = "FPS: —"
  document.getElementById("workerCount").innerText          = "Workers: —"
  if (typeof window.showProcessedFrame === "function") window.showProcessedFrame(null)
}

/* ============================================================
   DETECTION LOOP
============================================================ */
function startDetection() {
  const video  = document.getElementById("webcam")
  const canvas = document.getElementById("canvas")
  const ctx    = canvas.getContext("2d")
  let isProcessing = false

  detectionInterval = setInterval(async () => {
    if (isProcessing || !video.videoWidth) return
    isProcessing = true

    canvas.width  = video.videoWidth
    canvas.height = video.videoHeight
    ctx.drawImage(video, 0, 0)
    const frame = canvas.toDataURL("image/jpeg", 0.8)

    const r = await safeFetch("/detect_frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: frame })
    })

    if (r.ok && r.data) {
      const data = r.data

      // Show annotated frame in Processed Output panel
      if (data.frame && typeof window.showProcessedFrame === "function")
        window.showProcessedFrame(data.frame)

      // Update overlay pill
      const overlay = document.getElementById("detectionOverlay")
      if (data.violations && data.violations.length > 0) {
        overlay.innerText        = data.violations.join(" | ")
        overlay.style.background = "rgba(239,68,68,0.9)"
        overlay.style.color      = "#fff"
      } else if (data.detections && data.detections.length > 0) {
        overlay.innerText        = "Compliant"
        overlay.style.background = "rgba(34,197,94,0.85)"
        overlay.style.color      = "#000"
      } else {
        overlay.innerText        = "No person detected"
        overlay.style.background = "rgba(6,182,212,0.9)"
        overlay.style.color      = "#000"
      }

      if (data.worker_count !== undefined)
        document.getElementById("workerCount").innerText = "Workers: " + data.worker_count

      totalFramesProcessed++
      if (data.detections && data.detections.length > 0) totalDetections++
      if (typeof window.updateViolationStats === "function")
        window.updateViolationStats({ frames: totalFramesProcessed, detections: totalDetections })
    }

    frameCount++
    const now = Date.now()
    if (now - lastFpsTime >= 1000) {
      document.getElementById("fpsDisplay").innerText = "FPS: " + frameCount
      frameCount = 0; lastFpsTime = now
    }
    isProcessing = false
  }, 500)
}

/* ============================================================
   STATS
============================================================ */
async function loadStats() {
  const r = await safeFetch("/stats")
  if (!r.ok || !r.data) return
  const { helmet = 0, vest = 0, both = 0 } = r.data
  document.getElementById("helmetCount").innerText     = helmet
  document.getElementById("totalViolations").innerText = helmet + vest + both
  if (typeof window.updateViolationStats === "function")
    window.updateViolationStats({ helmet, vest, both, frames: totalFramesProcessed, detections: totalDetections })
}

/* ============================================================
   ALERTS
============================================================ */
async function loadAlerts() {
  const r = await safeFetch("/alerts")
  if (!r.ok || !r.data) return
  const data = r.data

  const dc = document.getElementById("alertsList")
  const ac = document.getElementById("alertsPageList")
  if (dc) dc.innerHTML = ""
  if (ac) ac.innerHTML = ""

  if (data.length === 0) {
    if (dc) dc.innerHTML = '<div class="no-data">No alerts yet</div>'
    if (ac) ac.innerHTML = '<div class="no-data">No alerts yet</div>'
    if (typeof window.updateAlertCount === "function") window.updateAlertCount(0)
    return
  }

  // Sound on new alert
  const latest = data[data.length - 1]
  if (latest && latest.message !== lastAlertMessage) {
    new Audio("/static/sounds/alarm.mp3").play().catch(() => {})
    lastAlertMessage = latest.message
  }

  // Dashboard mini-list (latest 6)
  if (dc) {
    data.slice().reverse().slice(0, 6).forEach(alert => {
      const type = alert.message || "Violation"
      const tag  = type.toLowerCase().includes("helmet") && type.toLowerCase().includes("vest") ? "yellow"
                 : type.toLowerCase().includes("helmet") ? "red" : "orange"
      const thumb = alert.image
        ? `<div class="alert-thumb"><img src="${alert.image}" alt="snap"></div>`
        : `<div class="alert-thumb"><svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:var(--text-muted);fill:none;stroke-width:2"><use href="#i-alert"/></svg></div>`
      dc.innerHTML += `
        <div class="alert-row">
          <span class="alert-time">${alert.time || ""}</span>
          ${thumb}
          <div class="alert-info">
            <span class="alert-cam">${alert.camera || "Camera 1"}</span>
            <span class="vtag ${tag}">${type}</span>
          </div>
          <button class="view-btn" onclick="showPage('alerts')">View</button>
        </div>`
    })
  }

  // Full alerts page (all, most recent first, with snapshots)
  if (ac) {
    data.slice().reverse().forEach(alert => {
      const type  = alert.message || "Violation"
      const color = type.toLowerCase().includes("helmet") ? "red" : "orange"
      const snap  = alert.image
        ? `<div class="ac-snap"><img src="${alert.image}" alt="snap" onerror="this.parentElement.innerHTML='<svg viewBox=\\'0 0 24 24\\'><use href=\\'#i-image\\'/></svg>'"></div>`
        : `<div class="ac-snap"><svg viewBox="0 0 24 24"><use href="#i-image"/></svg></div>`
      ac.innerHTML += `
        <div class="alert-card">
          ${snap}
          <div class="ac-icon ${color}">
            <svg viewBox="0 0 24 24" style="width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:2"><use href="#i-alert"/></svg>
          </div>
          <div class="ac-body">
            <div class="ac-title">${type}</div>
            <div class="ac-meta">${alert.camera || "Camera 1"} &nbsp;·&nbsp; ${alert.time || ""}</div>
          </div>
        </div>`
    })
  }

  if (typeof window.updateAlertCount === "function") window.updateAlertCount(data.length)
}

/* ============================================================
   ANALYTICS
   ✅ Called both on page load (below) AND when user navigates to Analytics tab.
============================================================ */
async function loadAnalytics() {
  const r = await safeFetch("/analytics")
  if (!r.ok || !r.data) {
    console.error("[Analytics] Failed to load:", r.status)
    return
  }
  const data     = r.data
  const insights = data.insights || {}

  const i1 = document.getElementById("insight1")
  const i2 = document.getElementById("insight2")
  const i3 = document.getElementById("insight3")
  if (i1) i1.innerText = "Most frequent violation: " + (insights.most_frequent || "—")
  if (i2) i2.innerText = "Peak violation time: "     + (insights.peak_time     || "—")
  if (i3) i3.innerText = "Total violations: "        + (insights.total         || 0)

  analyticsData = data
  renderSelectedChart()
}

function renderSelectedChart() {
  if (!analyticsData) return
  let type   = document.getElementById("chartSelector").value
  const canvas = document.getElementById("analyticsChart")
  if (!canvas) return
  const ctx = canvas.getContext("2d")
  if (analyticsChart) { analyticsChart.destroy(); analyticsChart = null; }

  if (type === "matrix") {
    const h = analyticsData.helmet, v = analyticsData.vest, mx = Math.max(h, v, 1)
    analyticsChart = new Chart(ctx, {
      type: "matrix",
      data: { datasets: [{ label: "Heatmap",
        data: [{ x:"Helmet", y:"Violations", v:h }, { x:"Vest", y:"Violations", v:v }],
        backgroundColor: c => `rgba(239,68,68,${c.dataset.data[c.dataIndex].v / mx})`,
        width: () => 100, height: () => 100
      }]},
      options: { responsive: true, maintainAspectRatio: false,
        scales: { x: { type:"category", labels:["Helmet","Vest"] }, y: { type:"category", labels:["Violations"] } },
        plugins: { tooltip: { callbacks: { label: c => `${c.raw.x}: ${c.raw.v}` } } }
      }
    })
    return
  }

  if (type === "timeline") {
    analyticsChart = new Chart(ctx, {
      type: "line",
      data: { labels: analyticsData.times, datasets: [
        { label:"Helmet Violations", data:analyticsData.helmet_series, borderWidth:2, fill:false, borderColor:"#ef4444" },
        { label:"Vest Violations",   data:analyticsData.vest_series,   borderWidth:2, fill:false, borderColor:"#f97316" }
      ]},
      options: { responsive: true, maintainAspectRatio: false }
    })
    return
  }

  let indexAxis
  if (type === "horizontal") { type = "bar"; indexAxis = "y"; }

  analyticsChart = new Chart(ctx, {
    type: type,
    data: {
      labels: ["Helmet Missing", "Vest Missing"],
      datasets: [{ label: "Violations",
        data: [analyticsData.helmet, analyticsData.vest],
        backgroundColor: ["rgba(239,68,68,0.7)", "rgba(249,115,22,0.7)"],
        borderColor: ["#ef4444", "#f97316"],
        borderWidth: 1
      }]
    },
    options: { responsive: true, maintainAspectRatio: false, ...(indexAxis ? { indexAxis } : {}) }
  })
}

/* ============================================================
   LOGS
============================================================ */
async function loadLogs() {
  const r = await safeFetch("/logs")
  if (!r.ok || !r.data) return
  const table = document.getElementById("logsTable")
  if (!table) return
  table.innerHTML = ""
  r.data.forEach(log => {
    const vtype = log.violation_type || ""
    const color = vtype.toLowerCase().includes("helmet") ? "red" : "orange"
    table.innerHTML += `
      <tr>
        <td>${new Date(log.timestamp).toLocaleTimeString()}</td>
        <td>${log.camera_id}</td>
        <td><span class="vtag ${color}">${vtype}</span></td>
        <td>${log.confidence}</td>
      </tr>`
  })
}

/* ============================================================
   VIDEO UPLOAD
   safeFetch handles the case where the server returns HTML 500
   instead of JSON — the error message is shown to the user.
============================================================ */
async function uploadVideo() {
  const fileInput = document.getElementById("videoInput")
  const file      = fileInput.files[0]
  const btn       = document.getElementById("uploadBtn")
  if (!file) { alert("Please select a video file first."); return; }

  btn.disabled  = true
  btn.innerHTML = `<svg viewBox="0 0 24 24" style="width:13px;height:13px;stroke:currentColor;fill:none;stroke-width:2;animation:_spin .8s linear infinite"><circle cx="12" cy="12" r="10" stroke-dasharray="60" stroke-dashoffset="20"/></svg> Processing…`
  if (!document.getElementById("_spinStyle")) {
    const s = document.createElement("style"); s.id = "_spinStyle"
    s.textContent = "@keyframes _spin{to{transform:rotate(360deg)}}"; document.head.appendChild(s)
  }

  const formData = new FormData()
  formData.append("video", file)

  const r = await safeFetch("/upload", { method: "POST", body: formData })

  if (r.ok && r.data && r.data.video_url) {
    // ✅ Show processed video panel
    if (typeof window.showProcessedVideo === "function")
      window.showProcessedVideo(r.data.video_url)
  } else {
    // Show the actual error from the server (not a generic message)
    const msg = r.data && r.data.error
      ? r.data.error
      : `Server returned status ${r.status}. Check the Flask console for the full traceback.`
    alert("Upload failed: " + msg)
    console.error("[Upload] Server error:", r.data || r.raw)
  }

  btn.disabled  = false
  btn.innerHTML = `<svg viewBox="0 0 24 24" style="width:13px;height:13px;stroke:currentColor;fill:none;stroke-width:2"><use href="#i-upload"/></svg> Upload &amp; Analyze`
}

/* ============================================================
   POLLING + INITIAL LOAD
   ✅ Analytics is loaded on startup so the chart is ready
      even before the user clicks the Analytics tab.
============================================================ */
setInterval(loadLogs,   3000)
setInterval(loadStats,  2000)
setInterval(loadAlerts, 3000)

loadStats()
loadAlerts()
loadLogs()
loadAnalytics()   // ← load on startup so chart is pre-populated