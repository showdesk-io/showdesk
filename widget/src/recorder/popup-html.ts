/**
 * Popup HTML builder — generates a self-contained HTML page for the
 * recording popup window.
 *
 * The popup is opened as a blob URL (inheriting the client site's origin)
 * so BroadcastChannel works. All JS/CSS is inlined — zero external deps.
 *
 * The popup handles:
 * - getDisplayMedia / getUserMedia capture
 * - MediaRecorder lifecycle
 * - BroadcastChannel communication with the widget
 * - Self-upload of the recording blob via the Showdesk API
 * - Duration guard (5-min notifications)
 * - Mic mute toggle
 */

export type PopupRecordingMode = "screen" | "audio";

export interface PopupConfig {
  token: string;
  apiUrl: string;
  sessionId: string;
  ticketId: string | null;
  color: string;
  /** "screen" for getDisplayMedia + mic, "audio" for mic-only. */
  mode: PopupRecordingMode;
}

export function buildPopupHtml(cfg: PopupConfig): string {
  // Escape for safe embedding in JS string literals inside the HTML
  const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, "&quot;");

  const isAudio = cfg.mode === "audio";
  const title = isAudio ? "Audio Recording" : "Screen Recording";
  const startLabel = isAudio ? "Start Microphone" : "Start Screen Capture";
  const bodyType = isAudio ? "audio" : "video";
  const fileExt = isAudio ? "webm" : "webm";

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Showdesk — ${title}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#1a1a2e;color:#e0e0e0;overflow:hidden;user-select:none}
.popup{display:flex;flex-direction:column;height:100vh;padding:12px 16px}
.header{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.header svg{flex-shrink:0}
.header h1{font-size:13px;font-weight:600;color:#fff}
.status-area{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px}
.rec-indicator{display:flex;align-items:center;gap:8px}
.rec-dot{width:10px;height:10px;border-radius:50%;background:#ef4444;animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.timer{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums;color:#fff}
.controls{display:flex;gap:8px;margin-top:12px}
.controls button,.btn-start{padding:8px 16px;border:none;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;display:flex;align-items:center;gap:6px;transition:opacity .15s}
.controls button:hover,.btn-start:hover{opacity:.85}
.btn-start{background:${esc(cfg.color)};color:#fff;font-size:15px;font-weight:600;padding:12px 24px}
.btn-mute{background:#334155;color:#e0e0e0}
.btn-mute.muted{background:#f59e0b;color:#000}
.btn-stop{background:#ef4444;color:#fff;font-weight:600}
.upload-area{text-align:center}
.progress-bar{width:100%;height:6px;background:#334155;border-radius:3px;overflow:hidden;margin:12px 0}
.progress-fill{height:100%;background:${esc(cfg.color)};border-radius:3px;transition:width .3s}
.done-area{text-align:center}
.done-area .check{font-size:36px;margin-bottom:8px}
.done-area p{color:#a0a0a0;font-size:13px}
.warning-banner{background:#f59e0b;color:#000;padding:6px 12px;border-radius:6px;font-size:12px;font-weight:500;text-align:center;margin-bottom:8px;animation:fadeIn .3s}
@keyframes fadeIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.error-area{text-align:center;color:#ef4444}
.start-hint{font-size:12px;color:#a0a0a0;margin-top:8px}
.hidden{display:none!important}
</style>
</head>
<body>
<div class="popup">
  <div class="header">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="${esc(cfg.color)}" stroke-width="2">
      <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
    </svg>
    <h1>${title}</h1>
  </div>
  <div id="warning-slot"></div>
  <div id="view-start" class="status-area">
    <button class="btn-start" id="btn-start">${startLabel}</button>
    <p class="start-hint">Your browser requires a click to begin capture</p>
  </div>
  <div id="view-recording" class="status-area hidden">
    <div class="rec-indicator"><div class="rec-dot"></div><span style="font-size:12px;color:#a0a0a0">Recording</span></div>
    <div class="timer" id="timer">0:00</div>
    <div class="controls">
      <button class="btn-mute" id="btn-mute" title="Toggle microphone">🎤 Mic</button>
      <button class="btn-stop" id="btn-stop">⏹ Stop</button>
    </div>
  </div>
  <div id="view-upload" class="status-area hidden">
    <div class="upload-area">
      <p style="color:#fff;font-size:15px;font-weight:600">Uploading…</p>
      <div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>
      <p id="upload-detail" style="color:#a0a0a0;font-size:12px">0%</p>
    </div>
  </div>
  <div id="view-done" class="status-area hidden">
    <div class="done-area">
      <div class="check">✓</div>
      <p style="color:#fff;font-size:15px;font-weight:600;margin-bottom:4px">Recording uploaded!</p>
      <p id="close-msg">This window will close in <span id="close-countdown">3</span>s…</p>
    </div>
  </div>
  <div id="view-error" class="status-area hidden">
    <div class="error-area">
      <p style="font-size:15px;font-weight:600;margin-bottom:4px">Recording failed</p>
      <p id="error-detail" style="font-size:12px"></p>
    </div>
  </div>
</div>

<script>
(function() {
  'use strict';

  /* ---- Config ---- */
  var CFG = {
    token: '${esc(cfg.token)}',
    apiUrl: '${esc(cfg.apiUrl)}',
    sessionId: '${esc(cfg.sessionId)}',
    ticketId: ${cfg.ticketId ? "'" + esc(cfg.ticketId) + "'" : "null"},
    mode: '${cfg.mode}',
    bodyType: '${bodyType}',
    fileExt: '${fileExt}',
  };
  var CHANNEL_NAME = 'showdesk-recording';
  var WARN_INTERVAL = 5 * 60 * 1000;

  /* ---- State ---- */
  var channel = new BroadcastChannel(CHANNEL_NAME);
  var mediaRecorder = null;
  var chunks = [];
  var streams = [];
  var audioCtx = null;
  var audioDest = null;
  var micSource = null;
  var audioOn = true;
  var elapsed = 0;
  var timerHandle = null;
  var warnHandle = null;
  var isUploading = false;

  /* ---- DOM refs ---- */
  var $timer = document.getElementById('timer');
  var $btnStart = document.getElementById('btn-start');
  var $btnMute = document.getElementById('btn-mute');
  var $btnStop = document.getElementById('btn-stop');
  var $viewStart = document.getElementById('view-start');
  var $viewRec = document.getElementById('view-recording');
  var $viewUpload = document.getElementById('view-upload');
  var $viewDone = document.getElementById('view-done');
  var $viewError = document.getElementById('view-error');
  var $progressFill = document.getElementById('progress-fill');
  var $uploadDetail = document.getElementById('upload-detail');
  var $errorDetail = document.getElementById('error-detail');
  var $warningSlot = document.getElementById('warning-slot');
  var $closeCountdown = document.getElementById('close-countdown');

  /* ---- Helpers ---- */
  function show(el) { el.classList.remove('hidden'); }
  function hide(el) { el.classList.add('hidden'); }

  function formatTime(s) {
    var m = Math.floor(s / 60);
    var sec = s % 60;
    return m + ':' + (sec < 10 ? '0' : '') + sec;
  }

  function send(msg) {
    try { channel.postMessage(msg); } catch(e) {}
  }

  function getSupportedMime(isAudioOnly) {
    if (isAudioOnly) {
      var audioTypes = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
      for (var j = 0; j < audioTypes.length; j++) {
        if (MediaRecorder.isTypeSupported(audioTypes[j])) return audioTypes[j];
      }
      return 'audio/webm';
    }
    var types = [
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm',
      'video/mp4'
    ];
    for (var i = 0; i < types.length; i++) {
      if (MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return 'video/webm';
  }

  /* ---- Recording ---- */
  async function startRecording() {
    var isAudioOnly = CFG.mode === 'audio';
    try {
      var tracks = [];

      if (!isAudioOnly) {
        /* Screen capture */
        var displayStream = await navigator.mediaDevices.getDisplayMedia({
          video: { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } },
          audio: true,
          selfBrowserSurface: 'include',
          preferCurrentTab: true,
        });
        streams.push(displayStream);
        displayStream.getAudioTracks().forEach(function(t) { tracks.push(t); });
        displayStream.getVideoTracks().forEach(function(t) { tracks.push(t); });

        // Stop recording if user ends screen share via browser UI
        displayStream.getVideoTracks().forEach(function(t) {
          t.onended = function() { stopRecording(); };
        });
      }

      /* Microphone via AudioContext (allows mute without stopping recorder) */
      try {
        var micStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true }
        });
        streams.push(micStream);
        audioCtx = new AudioContext();
        audioDest = audioCtx.createMediaStreamDestination();
        micSource = audioCtx.createMediaStreamSource(micStream);
        micSource.connect(audioDest);
        audioDest.stream.getAudioTracks().forEach(function(t) { tracks.push(t); });
      } catch(e) {
        console.warn('[Showdesk Popup] Mic denied:', e);
        if (isAudioOnly) throw new Error('Microphone access denied');
      }

      if (tracks.length === 0) throw new Error('No media tracks available');

      var mimeType = getSupportedMime(isAudioOnly);
      var combined = new MediaStream(tracks);
      var recOptions = { mimeType: mimeType };
      if (!isAudioOnly) recOptions.videoBitsPerSecond = 2500000;
      mediaRecorder = new MediaRecorder(combined, recOptions);
      chunks = [];

      mediaRecorder.ondataavailable = function(e) {
        if (e.data.size > 0) chunks.push(e.data);
      };

      mediaRecorder.onstop = function() {
        var blob = new Blob(chunks, { type: mimeType });
        cleanupStreams();
        send({ type: 'recording-stopped', blobSize: blob.size });
        uploadBlob(blob);
      };

      mediaRecorder.start(isAudioOnly ? 100 : 1000);

      // Switch from start view to recording view
      hide($viewStart);
      show($viewRec);

      // Timer
      elapsed = 0;
      timerHandle = setInterval(function() {
        elapsed++;
        $timer.textContent = formatTime(elapsed);
      }, 1000);

      // Duration guard
      var warnCount = 0;
      warnHandle = setInterval(function() {
        warnCount++;
        var mins = warnCount * 5;
        showWarning('Recording for ' + mins + ' minutes');
        send({ type: 'duration-warning', minutes: mins });
      }, WARN_INTERVAL);

      send({ type: 'recording-started' });
    } catch(e) {
      send({ type: 'recording-error', error: e.message || 'Failed to start' });
      showError(e.message || 'Failed to start capture');
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    if (timerHandle) { clearInterval(timerHandle); timerHandle = null; }
    if (warnHandle) { clearInterval(warnHandle); warnHandle = null; }
  }

  function cleanupStreams() {
    streams.forEach(function(s) {
      s.getTracks().forEach(function(t) { t.stop(); });
    });
    streams = [];
    if (micSource) { micSource.disconnect(); micSource = null; }
    if (audioDest) { audioDest.stream.getTracks().forEach(function(t) { t.stop(); }); audioDest = null; }
    if (audioCtx) { audioCtx.close().catch(function(){}); audioCtx = null; }
  }

  /* ---- Upload ---- */
  function uploadBlob(blob) {
    isUploading = true;
    hide($viewRec);
    show($viewUpload);
    send({ type: 'upload-started' });

    var form = new FormData();
    form.append('file', blob, 'recording-' + Date.now() + '.' + CFG.fileExt);
    form.append('body_type', CFG.bodyType);
    if (CFG.ticketId) form.append('ticket_id', CFG.ticketId);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', CFG.apiUrl + '/tickets/widget_message_attachment/');
    xhr.setRequestHeader('X-Widget-Token', CFG.token);
    xhr.setRequestHeader('X-Widget-Session', CFG.sessionId);
    xhr.timeout = 600000;

    xhr.upload.onprogress = function(e) {
      if (e.lengthComputable) {
        var pct = Math.round((e.loaded / e.total) * 100);
        $progressFill.style.width = pct + '%';
        $uploadDetail.textContent = pct + '% — ' + formatBytes(e.loaded) + ' / ' + formatBytes(e.total);
        send({ type: 'upload-progress', percent: pct });
      }
    };

    xhr.onload = function() {
      isUploading = false;
      if (xhr.status >= 200 && xhr.status < 300) {
        var data = JSON.parse(xhr.responseText);
        send({ type: 'upload-complete', ticketId: data.ticket_id, messageId: data.message_id });
        showDone();
      } else {
        var errMsg = 'Upload failed (HTTP ' + xhr.status + ')';
        send({ type: 'upload-failed', error: errMsg });
        showError(errMsg);
      }
    };

    xhr.onerror = function() {
      isUploading = false;
      send({ type: 'upload-failed', error: 'Network error' });
      showError('Network error — check your connection');
    };

    xhr.ontimeout = function() {
      isUploading = false;
      send({ type: 'upload-failed', error: 'Upload timed out' });
      showError('Upload timed out');
    };

    xhr.send(form);
  }

  function formatBytes(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1048576).toFixed(1) + ' MB';
  }

  /* ---- Views ---- */
  function showDone() {
    hide($viewUpload);
    show($viewDone);
    var count = 3;
    var h = setInterval(function() {
      count--;
      $closeCountdown.textContent = count;
      if (count <= 0) {
        clearInterval(h);
        window.close();
      }
    }, 1000);
  }

  function showError(msg) {
    hide($viewStart);
    hide($viewRec);
    hide($viewUpload);
    $errorDetail.textContent = msg;
    show($viewError);
  }

  function showWarning(msg) {
    var el = document.createElement('div');
    el.className = 'warning-banner';
    el.textContent = msg;
    $warningSlot.innerHTML = '';
    $warningSlot.appendChild(el);
    setTimeout(function() { el.remove(); }, 10000);
  }

  /* ---- Controls ---- */
  $btnStart.onclick = function() { startRecording(); };
  $btnStop.onclick = function() { stopRecording(); };

  $btnMute.onclick = function() {
    if (!audioDest) return;
    audioOn = !audioOn;
    audioDest.stream.getAudioTracks().forEach(function(t) { t.enabled = audioOn; });
    $btnMute.textContent = audioOn ? '🎤 Mic' : '🔇 Muted';
    $btnMute.classList.toggle('muted', !audioOn);
  };

  /* ---- BroadcastChannel ---- */
  channel.onmessage = function(e) {
    var msg = e.data;
    if (!msg || !msg.type) return;
    switch (msg.type) {
      case 'stop-requested':
        stopRecording();
        break;
      case 'status-request':
        send({
          type: 'status-response',
          isRecording: !!(mediaRecorder && mediaRecorder.state === 'recording'),
          elapsed: elapsed,
          isUploading: isUploading,
        });
        break;
    }
  };

  /* ---- Lifecycle ---- */
  window.addEventListener('beforeunload', function(e) {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      e.preventDefault();
      e.returnValue = 'Recording in progress — are you sure?';
    }
    send({ type: 'popup-closed' });
  });
})();
</script>
</body>
</html>`;
}
