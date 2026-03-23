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