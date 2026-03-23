from flask import Flask, render_template, request, jsonify, send_from_directory
import cv2
import base64
import numpy as np
import os
from datetime import datetime
from ultralytics import YOLO
from database import insert_violation, get_logs

app = Flask(__name__)

alerts = []
violation_logs = []
last_alert_time = {}
last_db_insert_time = {}
model = YOLO("model/best.pt")

helmet_violations = 0
vest_violations = 0

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
SNAPSHOT_FOLDER = os.path.join(os.getcwd(), "snapshots")
os.makedirs(SNAPSHOT_FOLDER, exist_ok=True)
def check_violations(detections):

    helmet_count = detections.count("helmet")
    vest_count = detections.count("vest")

    violations = []

    # If helmets are too few → violation
    if helmet_count < 1:
        violations.append("No Helmet")

    # If vests are too few → violation
    if vest_count < 1:
        violations.append("No Safety Vest")

    return violations
@app.route("/")
def dashboard():
    return render_template("index.html")

#===============ANALYTICS================
@app.route("/analytics")
def analytics():

    data = get_logs()

    helmet = 0
    vest = 0

    time_map = {}   # { "18:22": {helmet:2, vest:1} }

    for v in data:

        time_key = datetime.fromisoformat(v["timestamp"]).strftime("%H:%M")

        if time_key not in time_map:
            time_map[time_key] = {"helmet": 0, "vest": 0}

        if v["violation_type"] == "No Helmet":
            helmet += 1
            time_map[time_key]["helmet"] += 1

        elif v["violation_type"] == "No Safety Vest":
            vest += 1
            time_map[time_key]["vest"] += 1

    # sort time
    sorted_times = sorted(time_map.keys())

    helmet_series = [time_map[t]["helmet"] for t in sorted_times]
    vest_series = [time_map[t]["vest"] for t in sorted_times]
 
    # ================= INSIGHTS =================

    most_frequent = "Helmet" if helmet > vest else "Vest"

# find peak time
    peak_time = None
    max_count = 0

    for t in time_map:
        total = time_map[t]["helmet"] + time_map[t]["vest"]
        if total > max_count:
            max_count = total
            peak_time = t

     


    return jsonify({
    "helmet": helmet,
    "vest": vest,
    "times": sorted_times,
    "helmet_series": helmet_series,
    "vest_series": vest_series,

    # ✅ NEW
    "insights": {
        "most_frequent": most_frequent,
        "peak_time": peak_time,
        "total": helmet + vest
    }
})
# ===================== LIVE CAMERA =====================
@app.route("/detect_frame", methods=["POST"])
def detect_frame():

    global helmet_violations, vest_violations, alerts, last_alert_time

    data = request.json["image"]
    encoded = data.split(",")[1]

    img_bytes = base64.b64decode(encoded)
    np_img = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(np_img, cv2.IMREAD_COLOR)

    results = model(frame)[0]

    detections = []
    confidences = []

    # ================= DETECTION =================
    for box in results.boxes:

        cls = int(box.cls[0])
        label = model.names[cls]
        conf = float(box.conf[0])

        detections.append(label)
        confidences.append(conf)

        x1, y1, x2, y2 = map(int, box.xyxy[0])

        # default green
        color = (0, 255, 0)

        # 🚨 violation = red
        if label in ["no-helmet", "no-vest"]:
            color = (0, 0, 255)

        display_label = label.upper()

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, display_label, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, color, 2)

    # ================= VIOLATION CHECK =================
    violations = check_violations(detections)

    filename = None

    if violations:
        filename = save_snapshot(frame, "live")  # ✅ consistent usage

    # ================= ALERT + DB =================
    import time
    current_time = time.time()
    time_now = datetime.now().strftime("%H:%M:%S")

    camera_id = "Camera 1"

    for i, v in enumerate(violations):

        alert_key = f"{v}_{camera_id}"
        db_key = f"{v}_{camera_id}"

    # ✅ ALERT CONTROL
    if alert_key not in last_alert_time or current_time - last_alert_time[alert_key] > 10:
        alerts.append({
            "message": f"{v} detected",
            "camera": camera_id,
            "time": time_now,
            "image": f"/snapshots/{filename}" if filename else None
        })
        last_alert_time[alert_key] = current_time

    # ✅ DB CONTROL (MAIN FIX)
    if db_key not in last_db_insert_time or current_time - last_db_insert_time[db_key] > 10:

          conf = confidences[i] if i < len(confidences) else 0.9

          insert_violation(
            violation_type=v,
            confidence=round(conf, 2),
            camera_id=camera_id
        )

          last_db_insert_time[db_key] = current_time

        # update counters ONLY when inserted
          if v == "No Helmet":
            helmet_violations += 1
          elif v == "No Safety Vest":
            vest_violations += 1
    # ================= RETURN FRAME =================
    _, buffer = cv2.imencode(".jpg", frame)
    encoded_frame = base64.b64encode(buffer).decode()

    return jsonify({
        "frame": f"data:image/jpeg;base64,{encoded_frame}"
    })


# ================= SNAPSHOT FUNCTION =================
def save_snapshot(frame, prefix="live"):

    filename = f"{prefix}_{datetime.now().strftime('%H%M%S%f')}.jpg"
    filepath = os.path.join(SNAPSHOT_FOLDER, filename)

    cv2.imwrite(filepath, frame)

    print("📸 SAVED:", filepath)

    return filename

@app.route("/snapshots_list")
def snapshots_list():

    files = os.listdir(SNAPSHOT_FOLDER)
    files = sorted(files, reverse=True)

    urls = [f"/snapshots/{f}" for f in files]

    return jsonify(urls)
# ================= SERVE SNAPSHOTS =================
@app.route("/snapshots/<filename>")
def get_snapshot(filename):
    full_path = os.path.join(SNAPSHOT_FOLDER, filename)

    print("Requested:", filename)
    print("Full path:", full_path)
    print("Exists:", os.path.exists(full_path))

    return send_from_directory(SNAPSHOT_FOLDER, filename)

# ===================== STATS =====================

@app.route("/stats")
def get_stats():
    try:
        data = get_logs()

        helmet = 0
        vest = 0

        for v in data:
            if v.get("violation_type") == "No Helmet":
                helmet += 1
            elif v.get("violation_type") == "No Safety Vest":
                vest += 1

        return jsonify({
            "total": len(data),
            "helmet": helmet,
            "vest": vest
        })

    except Exception as e:
        print("❌ STATS ERROR:", e)
        return jsonify({"total":0,"helmet":0,"vest":0})

# ===================== ALERTS =====================

@app.route("/alerts")
def get_alerts():
    return jsonify(alerts)


# ===================== LOGS =====================

@app.route("/logs")
def logs():

    data = get_logs()
    print("Logs from DB:", data)

    return jsonify(data)


# ===================== VIDEO UPLOAD =====================

@app.route("/upload", methods=["POST"])
def upload():

    global alerts, last_alert_time

    # ✅ Add processing alert
    alerts.append({
        "message": "Processing uploaded video...",
        "camera": "System",
        "time": datetime.now().strftime("%H:%M:%S")
    })

    file = request.files["video"]

    input_path = os.path.join(UPLOAD_FOLDER, file.filename)
    output_path = os.path.join(UPLOAD_FOLDER, "processed_" + file.filename)

    file.save(input_path)

    cap = cv2.VideoCapture(input_path)

    width = int(cap.get(3))
    height = int(cap.get(4))
    fps = cap.get(cv2.CAP_PROP_FPS)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_count = 0

    import time  # ✅ REQUIRED

    while True:

        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1

        # Skip frames
        if frame_count % 30 != 0:
            out.write(frame)
            continue

        results = model(frame)[0]

        detections = []
        confidences = []

        for box in results.boxes:

            cls = int(box.cls[0])
            label = model.names[cls]
            conf = float(box.conf[0])

            detections.append(label)
            confidences.append(conf)

            x1, y1, x2, y2 = map(int, box.xyxy[0])

            color = (0,255,0)
            if label in ["no-helmet", "no-vest"]:
                color = (0,0,255)

            cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
            cv2.putText(frame, label, (x1,y1-10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, color, 2)

        violations = check_violations(detections)
        filename = None

        if violations:
            filename = save_snapshot(frame, "upload")
        print("UPLOAD Detections:", detections)
        print("UPLOAD Violations:", violations)

        # ✅ DEFINE TIME HERE
        current_time = time.time()
        time_now = datetime.now().strftime("%H:%M:%S")

        for i, v in enumerate(violations):

            conf = confidences[i] if i < len(confidences) else 0.9

            print("Inserting (Upload):", v, conf)

            # ✅ Insert into DB
            key = f"{v}_Uploaded"

            if key not in last_db_insert_time or current_time - last_db_insert_time[key] > 10:
                insert_violation(
        violation_type=v,
        confidence=round(conf, 2),
        camera_id="Uploaded Video"
    )

                last_db_insert_time[key] = current_time
            # ✅ ADD ALERT (FIXED)
        camera_id = "Camera 1"  # or Uploaded Video

        alert_key = f"{v}_{camera_id}"

        if alert_key not in last_alert_time or current_time - last_alert_time[alert_key] > 10:
            alerts.append({
        "message": f"{v} detected",
        "camera": camera_id,
        "time": time_now,
        "image": f"/snapshots/{filename}" if filename else None
    })

            last_alert_time[alert_key] = current_time   
    out.write(frame)

    cap.release()
    out.release()

    return jsonify({
        "video_url": f"/uploads/processed_{file.filename}"
    })
@app.route("/test")
def test():
    print("TEST WORKING")
    return "OK"

# ===================== SERVE VIDEO =====================

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)


if __name__ == "__main__":
    app.run(debug=True)