from supabase_client import supabase

def insert_violation(violation_type, confidence, camera_id):

    data = {
        "violation_type": violation_type,
        "confidence": confidence,
        "camera_id": camera_id
    }

    try:
        response = supabase.table("violations").insert(data).execute()
        print("✅ INSERT SUCCESS:", response.data)
        return response

    except Exception as e:
        print("❌ INSERT ERROR:", e)
        return None


def get_logs():
    try:
        response = supabase.table("violations") \
            .select("*") \
            .order("timestamp", desc=True) \
            .limit(20) \
            .execute()

        print("DB FETCH SUCCESS:", response.data)
        return response.data

    except Exception as e:
        print("❌ DB FETCH ERROR:", e)
        return []