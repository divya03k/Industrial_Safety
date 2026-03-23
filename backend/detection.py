import cv2
from ultralytics import YOLO

from database import insert_violation
from violation_logic import check_violations

# Load trained model
model = YOLO("model/best.pt")


def detect_frame(frame):

    results = model(frame)[0]

    detections = []

    for box in results.boxes:

        cls = int(box.cls[0])
        label = model.names[cls]
        confidence = float(box.conf[0])

        detections.append(label)

        x1, y1, x2, y2 = map(int, box.xyxy[0])

        # Draw detection box
        cv2.rectangle(frame,(x1,y1),(x2,y2),(0,255,0),2)

        cv2.putText(
            frame,
            f"{label} {confidence:.2f}",
            (x1,y1-10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0,255,0),
            2
        )

    # Check violations
    violations = check_violations(detections)

    for v in violations:

        # Log violation in database
        insert_violation(
            violation_type=v,
            confidence=0.9,
            camera_id="Webcam-1"
        )

        # Display violation text
        cv2.putText(
            frame,
            v,
            (30,50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0,0,255),
            3
        )

    return frame