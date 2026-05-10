from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import cv2
import base64
import numpy as np
import os
import time
import subprocess
import traceback
from datetime import datetime
from ultralytics import YOLO

from backend.database import insert_violation, get_logs
app = Flask(__name__)

alerts              = []
violation_logs      = []
last_alert_time     = {}
last_db_insert_time = {}
model               = YOLO("model/best.pt")

helmet_violations = 0
vest_violations   = 0

UPLOAD_FOLDER   = "uploads"
SNAPSHOT_FOLDER = os.path.join(os.getcwd(), "snapshots")
os.makedirs(UPLOAD_FOLDER,   exist_ok=True)
os.makedirs(SNAPSHOT_FOLDER, exist_ok=True)


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def check_violations(detections):
    violations   = []
    labels_lower = [d.lower() for d in detections]
    has_helmet   = any("helmet" in l and "no" not in l for l in labels_lower)
    has_vest     = any(("vest" in l or "safety" in l) and "no" not in l for l in labels_lower)
    if not has_helmet:
        violations.append("No Helmet")
    if not has_vest:
        violations.append("No Safety Vest")
    return violations


def save_snapshot(frame, prefix="live"):
    filename = f"{prefix}_{datetime.now().strftime('%H%M%S%f')}.jpg"
    filepath = os.path.join(SNAPSHOT_FOLDER, filename)
    cv2.imwrite(filepath, frame)
    print(f"[SNAPSHOT] Saved: {filepath}")
    return filename


def encode_frame(frame):
    _, buffer = cv2.imencode(".jpg", frame)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer).decode()}"


def reencode_for_browser(raw_path, output_path):
    """
    Re-encode mp4v → H.264 so every browser can play it.
    -pix_fmt yuv420p  required for Safari
    -movflags faststart  enables streaming / seeking
    -an  skip audio (avoids errors if source has no audio)
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_path,
        "-vcodec", "libx264",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[FFMPEG ERROR]\n{result.stderr[-1000:]}")
            return False
        print(f"[FFMPEG] Re-encode done → {output_path}")
        return True
    except Exception as e:
        print(f"[FFMPEG EXCEPTION] {e}")
        return False


# ─────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────

# ── Silence the favicon 404 ────────────────
@app.route("/favicon.ico")
def favicon():
    return Response(status=204)   # 204 No Content — no icon, no error


@app.route("/")
def dashboard():
    return render_template("index.html")


# ── STATS ──────────────────────────────────
@app.route("/stats")
def get_stats():
    try:
        data   = get_logs()
        helmet = sum(1 for v in data if v.get("violation_type") == "No Helmet")
        vest   = sum(1 for v in data if v.get("violation_type") == "No Safety Vest")
        return jsonify({"total": len(data), "helmet": helmet, "vest": vest, "both": 0})
    except Exception as e:
        print(f"[STATS ERROR] {e}")
        return jsonify({"total": 0, "helmet": 0, "vest": 0, "both": 0})


# ── ALERTS ─────────────────────────────────
@app.route("/alerts")
def get_alerts():
    return jsonify(alerts)


# ── LOGS ───────────────────────────────────
@app.route("/logs")
def logs():
    try:
        return jsonify(get_logs())
    except Exception as e:
        print(f"[LOGS ERROR] {e}")
        return jsonify([])


# ── ANALYTICS ──────────────────────────────
@app.route("/analytics")
def analytics():
    try:
        data     = get_logs()
        helmet   = 0
        vest     = 0
        time_map = {}

        for v in data:
            try:
                time_key = datetime.fromisoformat(v["timestamp"]).strftime("%H:%M")
            except Exception:
                time_key = "00:00"

            if time_key not in time_map:
                time_map[time_key] = {"helmet": 0, "vest": 0}

            if v["violation_type"] == "No Helmet":
                helmet += 1
                time_map[time_key]["helmet"] += 1
            elif v["violation_type"] == "No Safety Vest":
                vest += 1
                time_map[time_key]["vest"] += 1

        sorted_times  = sorted(time_map.keys())
        helmet_series = [time_map[t]["helmet"] for t in sorted_times]
        vest_series   = [time_map[t]["vest"]   for t in sorted_times]
        most_frequent = "Helmet" if helmet >= vest else "Vest"

        peak_time, max_count = None, 0
        for t, counts in time_map.items():
            total = counts["helmet"] + counts["vest"]
            if total > max_count:
                max_count = total
                peak_time = t

        return jsonify({
            "helmet":        helmet,
            "vest":          vest,
            "times":         sorted_times,
            "helmet_series": helmet_series,
            "vest_series":   vest_series,
            "insights": {
                "most_frequent": most_frequent,
                "peak_time":     peak_time or "—",
                "total":         helmet + vest
            }
        })
    except Exception as e:
        print(f"[ANALYTICS ERROR] {e}")
        return jsonify({
            "helmet": 0, "vest": 0, "times": [], "helmet_series": [], "vest_series": [],
            "insights": {"most_frequent": "—", "peak_time": "—", "total": 0}
        })


# ── LIVE DETECTION ─────────────────────────
@app.route("/detect_frame", methods=["POST"])
def detect_frame():
    global helmet_violations, vest_violations
    try:
        data      = request.json["image"]
        encoded   = data.split(",")[1]
        img_bytes = base64.b64decode(encoded)
        np_img    = np.frombuffer(img_bytes, np.uint8)
        frame     = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"frame": data, "detections": [], "violations": [], "worker_count": 0})

        results     = model(frame)[0]
        detections  = []
        det_objects = []
        confidences = []

        for box in results.boxes:
            cls   = int(box.cls[0])
            label = model.names[cls]
            conf  = float(box.conf[0])
            detections.append(label)
            confidences.append(conf)
            det_objects.append({"label": label, "confidence": round(conf, 2)})

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            color = (0, 0, 255) if "no" in label.lower() else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label.upper(), (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        worker_count      = len(results.boxes)
        violations        = check_violations(detections)
        snapshot_filename = save_snapshot(frame, "live") if violations else None

        current_time = time.time()
        time_now     = datetime.now().strftime("%H:%M:%S")
        camera_id    = "Camera 1"

        for i, v in enumerate(violations):
            alert_key = f"{v}_{camera_id}"
            db_key    = f"{v}_{camera_id}"

            if alert_key not in last_alert_time or current_time - last_alert_time[alert_key] > 10:
                alerts.append({
                    "message": f"{v} detected",
                    "camera":  camera_id,
                    "time":    time_now,
                    "image":   f"/snapshots/{snapshot_filename}" if snapshot_filename else None
                })
                last_alert_time[alert_key] = current_time

            if db_key not in last_db_insert_time or current_time - last_db_insert_time[db_key] > 10:
                conf = confidences[i] if i < len(confidences) else 0.9
                insert_violation(violation_type=v, confidence=round(conf, 2), camera_id=camera_id)
                last_db_insert_time[db_key] = current_time
                if v == "No Helmet":
                    helmet_violations += 1
                elif v == "No Safety Vest":
                    vest_violations += 1

        return jsonify({
            "frame":        encode_frame(frame),
            "detections":   det_objects,
            "violations":   violations,
            "worker_count": worker_count
        })

    except Exception as e:
        print(f"[DETECT ERROR] {e}\n{traceback.format_exc()}")
        return jsonify({"frame": "", "detections": [], "violations": [], "worker_count": 0})


# ── SNAPSHOTS ──────────────────────────────
@app.route("/snapshots_list")
def snapshots_list():
    files = sorted(os.listdir(SNAPSHOT_FOLDER), reverse=True)
    return jsonify([f"/snapshots/{f}" for f in files])


@app.route("/snapshots/<filename>")
def get_snapshot(filename):
    return send_from_directory(SNAPSHOT_FOLDER, filename)


# ── VIDEO UPLOAD ───────────────────────────
@app.route("/upload", methods=["POST"])
def upload():
    """
    Pipeline:
      1. Save original file   → uploads/<name><ext>
      2. Annotate (OpenCV)    → uploads/raw_<name>.mp4   (mp4v — not browser-playable)
      3. Re-encode (FFmpeg)   → uploads/processed_<name>.mp4  (H.264 — browser-safe)

    The entire function is wrapped in try/except so any crash returns
    a JSON error instead of an HTML 500 page.
    """
    # Always respond with JSON — never let an exception reach Flask's HTML handler
    try:
        alerts.append({
            "message": "Processing uploaded video...",
            "camera":  "System",
            "time":    datetime.now().strftime("%H:%M:%S"),
            "image":   None
        })

        if "video" not in request.files:
            return jsonify({"error": "No video file in request"}), 400

        file = request.files["video"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Sanitise the filename
        original  = file.filename
        name_only = os.path.splitext(original)[0].replace(" ", "_")
        ext       = os.path.splitext(original)[1].lower() or ".mp4"

        input_path  = os.path.join(UPLOAD_FOLDER, name_only + ext)
        raw_path    = os.path.join(UPLOAD_FOLDER, "raw_"       + name_only + ".mp4")
        output_path = os.path.join(UPLOAD_FOLDER, "processed_" + name_only + ".mp4")

        # ── Step 1: save the uploaded file ──
        file.save(input_path)
        print(f"[UPLOAD] Saved: {input_path}  ({os.path.getsize(input_path)} bytes)")

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return jsonify({"error": f"OpenCV cannot open file: {input_path}"}), 400

        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps    = cap.get(cv2.CAP_PROP_FPS) or 20
        print(f"[UPLOAD] Video: {width}x{height} @ {fps:.1f} fps")

        if width == 0 or height == 0:
            cap.release()
            return jsonify({"error": "Could not read video dimensions — file may be corrupt"}), 400

        # ── Step 2: annotate frames with YOLO ──
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out    = cv2.VideoWriter(raw_path, fourcc, fps, (width, height))
        if not out.isOpened():
            cap.release()
            return jsonify({"error": "VideoWriter failed to open — check codec / disk space"}), 500

        frame_count       = 0
        snapshot_filename = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            results     = model(frame)[0]
            detections  = []
            confidences = []

            for box in results.boxes:
                cls   = int(box.cls[0])
                label = model.names[cls]
                conf  = float(box.conf[0])
                detections.append(label)
                confidences.append(conf)

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                color = (0, 0, 255) if "no" in label.lower() else (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, label.upper(), (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            violations = check_violations(detections)
            if violations and snapshot_filename is None:
                snapshot_filename = save_snapshot(frame, "upload")

            current_time = time.time()
            time_now     = datetime.now().strftime("%H:%M:%S")
            camera_id    = "Uploaded Video"

            for i, v in enumerate(violations):
                db_key    = f"{v}_{camera_id}"
                alert_key = f"{v}_{camera_id}"

                if db_key not in last_db_insert_time or current_time - last_db_insert_time[db_key] > 10:
                    conf_val = confidences[i] if i < len(confidences) else 0.9
                    insert_violation(violation_type=v, confidence=round(conf_val, 2), camera_id=camera_id)
                    last_db_insert_time[db_key] = current_time

                if alert_key not in last_alert_time or current_time - last_alert_time[alert_key] > 10:
                    alerts.append({
                        "message": f"{v} detected",
                        "camera":  camera_id,
                        "time":    time_now,
                        "image":   f"/snapshots/{snapshot_filename}" if snapshot_filename else None
                    })
                    last_alert_time[alert_key] = current_time

            out.write(frame)

        cap.release()
        out.release()
        print(f"[UPLOAD] OpenCV done — {frame_count} frames → {raw_path}")

        if frame_count == 0:
            return jsonify({"error": "Video has no readable frames"}), 400

        # ── Step 3: re-encode to H.264 so browsers can play it ──
        ok = reencode_for_browser(raw_path, output_path)
        if ok:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        else:
            # FFmpeg failed — serve the raw file as fallback
            print("[UPLOAD] FFmpeg failed — serving raw mp4v file (may not play in all browsers)")
            if os.path.exists(raw_path):
                os.rename(raw_path, output_path)

        return jsonify({"video_url": f"/uploads/processed_{name_only}.mp4"})

    except Exception as e:
        # Print full traceback to the Flask console so you can debug
        print(f"[UPLOAD CRASH]\n{traceback.format_exc()}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/test")
def test():
    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)