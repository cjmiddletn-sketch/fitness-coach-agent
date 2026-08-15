import os
import io
import json
import math
import requests
from typing import Dict, List, Any, Optional
from PIL import Image
import google.generativeai as genai

# -----------------------------------------------------------------------------
# 1. MacroFactor-Style True TDEE & Dynamic Expenditure Engine
# -----------------------------------------------------------------------------
def calculate_true_tdee(
    recent_checkins: List[Dict[str, Any]], 
    recent_nutrition: List[Dict[str, Any]], 
    baseline_tdee: float
) -> Dict[str, Any]:
    if len(recent_checkins) < 5 or len(recent_nutrition) < 5:
        return {
            "true_tdee": round(baseline_tdee),
            "confidence": "Low (Under 5 days logged)",
            "expenditure_drift": 0,
            "message": "Collecting baseline data. True TDEE matches formula estimate."
        }

    weight_start = recent_checkins[0]["weight_kg"]
    weight_end = recent_checkins[-1]["weight_kg"]
    delta_weight_kg = weight_end - weight_start
    days = len(recent_checkins)

    total_cal_intake = sum(item.get("cal", 0) or 0 for item in recent_nutrition)
    avg_daily_intake = total_cal_intake / max(1, len(recent_nutrition))

    # 1 kg body mass delta ~ 7700 kcal
    caloric_surplus_deficit_total = delta_weight_kg * 7700.0
    daily_surplus_deficit = caloric_surplus_deficit_total / max(1, days)
    
    calculated_true_tdee = avg_daily_intake - daily_surplus_deficit
    calculated_true_tdee = max(1400.0, min(4200.0, calculated_true_tdee))
    drift = calculated_true_tdee - baseline_tdee

    return {
        "true_tdee": round(calculated_true_tdee),
        "confidence": "High (14-day rolling metabolic balance)",
        "expenditure_drift": round(drift),
        "avg_daily_intake": round(avg_daily_intake),
        "delta_weight_kg": round(delta_weight_kg, 2)
    }

def calculate_tdee_and_macros(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str,
    aesthetic_focus: str = "abs_v_taper"
) -> Dict[str, Any]:
    if gender.lower() == "male":
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
    else:
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161

    multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "very_active": 1.725,
        "extra_active": 1.9
    }
    tdee = bmr * multipliers.get(activity_level.lower(), 1.55)

    if goal == "fat_loss":
        target_calories = tdee - 500
    elif goal == "hypertrophy":
        target_calories = tdee + 250
    elif goal == "strength":
        target_calories = tdee + 150
    else:
        target_calories = tdee

    min_floor = 1600 if gender.lower() == "male" else 1300
    target_calories = max(min_floor, target_calories)

    protein_mult = 2.2 if "abs" in aesthetic_focus else 2.0
    protein_g = round(protein_mult * weight_kg)
    fat_calories = target_calories * 0.25
    fat_g = round(fat_calories / 9.0)
    carb_calories = target_calories - ((protein_g * 4.0) + fat_calories)
    carb_g = max(50, round(carb_calories / 4.0))

    return {
        "bmr": round(bmr, 1),
        "tdee": round(tdee, 1),
        "target_calories": round(target_calories),
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carb_g": carb_g
    }

# -----------------------------------------------------------------------------
# 2. Workout Generator with Session Briefing & Core Architecture
# -----------------------------------------------------------------------------
def generate_workout_session(
    time_minutes: int,
    environment: str,
    split_type: str,
    joint_limitations: List[str],
    recovery_status: str,
    include_abs: bool = True
) -> Dict[str, Any]:
    
    is_gym = (environment.lower() == "gym")
    
    briefing_templates = {
        "Push": {
            "theme": "Push: Clavicular Pecs & Lateral Delts (V-Taper)",
            "target_groups": ["Upper Chest (Clavicular)", "Lateral Deltoids", "Triceps (Lateral Head)", "Upper Rectus Abdominis"],
            "objective": "Maximize clavicular chest tension with low-incline pressing while driving shoulder width with strict side raises.",
            "gym_exercises": [
                {"name": "Low-Incline DB Bench Press (30°)", "sets": 3, "reps": "8-10", "rpe": 8.0, "rest_s": 90, "target": "Upper Chest"},
                {"name": "Seated Cable Lateral Raise", "sets": 3, "reps": "12-15", "rpe": 8.5, "rest_s": 60, "target": "Lateral Delts"},
                {"name": "Machine Chest Press (Neutral Grip)", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 75, "target": "Mid/Lower Pecs"},
                {"name": "Cable Overhead Triceps Extension", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 60, "target": "Triceps Long Head"}
            ],
            "travel_exercises": [
                {"name": "Deficit Push-ups (Hands elevated)", "sets": 3, "reps": "12-15", "rpe": 8.0, "rest_s": 60, "target": "Chest"},
                {"name": "Dumbbell/Band Lateral Raise", "sets": 3, "reps": "15-20", "rpe": 8.5, "rest_s": 45, "target": "Lateral Delts"},
                {"name": "Diamond Push-ups or Chair Dips", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 60, "target": "Triceps"}
            ],
            "ab_finisher": {"name": "Kneeling High-Cable Rope Crunch", "travel_name": "Weighted Plank / Hollow Holds", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Rectus Abdominis"}
        },
        "Pull": {
            "theme": "Pull: Lat Width & Scapular Retraction",
            "target_groups": ["Lats (Iliac/Thoracic)", "Rear Delts", "Brachialis & Biceps", "Lower Rectus Abdominis"],
            "objective": "Build back width and V-taper tapering to the waist with full-stretch vertical and horizontal rowing mechanics.",
            "gym_exercises": [
                {"name": "Neutral-Grip Lat Pulldown", "sets": 3, "reps": "8-10", "rpe": 8.0, "rest_s": 90, "target": "Lat Width"},
                {"name": "Chest-Supported Dumbbell Row", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 75, "target": "Upper Back / Rhomboids"},
                {"name": "Reverse Pec-Deck Flye", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 60, "target": "Rear Delts"},
                {"name": "Incline Dumbbell Biceps Curl", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 60, "target": "Biceps (Stretch)"}
            ],
            "travel_exercises": [
                {"name": "Single-Arm Dumbbell Row", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 60, "target": "Lats"},
                {"name": "Band Pull-Aparts / Rear Delt Flyes", "sets": 3, "reps": "15-20", "rpe": 9.0, "rest_s": 45, "target": "Rear Delts"},
                {"name": "Standing Dumbbell Hammer Curls", "sets": 3, "reps": "12-15", "rpe": 8.5, "rest_s": 45, "target": "Brachialis"}
            ],
            "ab_finisher": {"name": "Hanging Leg / Knee Raises", "travel_name": "Lying Reverse Crunches", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Lower Abs"}
        },
        "Legs": {
            "theme": "Legs: Quad Sweep, Glute & Core Stability",
            "target_groups": ["Quadriceps", "Hamstrings", "Glutes", "Anti-Extension Core"],
            "objective": "Develop lower-body athletic power while maintaining trunk rigidity and protecting knee/spine joints.",
            "gym_exercises": [
                {"name": "Leg Press (Feet Mid-Low)", "sets": 3, "reps": "10-12", "rpe": 8.0, "rest_s": 90, "target": "Quad Sweep"},
                {"name": "Seated or Lying Hamstring Curl", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 75, "target": "Hamstrings"},
                {"name": "Dumbbell Romanian Deadlift (RDL)", "sets": 3, "reps": "8-10", "rpe": 8.0, "rest_s": 90, "target": "Posterior Chain"},
                {"name": "Standing Calf Raises", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Calves"}
            ],
            "travel_exercises": [
                {"name": "Dumbbell Goblet Squats", "sets": 3, "reps": "12-15", "rpe": 8.5, "rest_s": 60, "target": "Quads"},
                {"name": "Single-Leg Bulgarian Split Squats", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 60, "target": "Glutes & Quads"},
                {"name": "Single-Leg Dumbbell RDL", "sets": 3, "reps": "10-12", "rpe": 8.0, "rest_s": 60, "target": "Hamstrings"}
            ],
            "ab_finisher": {"name": "Ab Wheel Rollouts / Cable Pallof Press", "travel_name": "Long-Lever Plank Hold", "sets": 3, "reps": "10-12", "rpe": 9.0, "rest_s": 45, "target": "Deep Core"}
        },
        "Upper": {
            "theme": "Upper Body Density & V-Taper Power",
            "target_groups": ["Pectorals", "Lats & Mid-Back", "Lateral Delts", "Arms & Abs"],
            "objective": "High-efficiency antagonist pairings targeting clavicular chest, lat width, and shoulder cap.",
            "gym_exercises": [
                {"name": "Low-Incline DB Bench Press", "sets": 3, "reps": "8-10", "rpe": 8.0, "rest_s": 75, "target": "Chest"},
                {"name": "Neutral-Grip Lat Pulldown", "sets": 3, "reps": "8-10", "rpe": 8.0, "rest_s": 75, "target": "Lats"},
                {"name": "Dumbbell Lateral Raise", "sets": 3, "reps": "12-15", "rpe": 8.5, "rest_s": 45, "target": "Lateral Delts"},
                {"name": "Triceps Rope Pushdown ↔ DB Hammer Curl", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Arms Superset"}
            ],
            "travel_exercises": [
                {"name": "Push-ups (Pause at bottom)", "sets": 3, "reps": "12-15", "rpe": 8.0, "rest_s": 60, "target": "Chest"},
                {"name": "Single-Arm DB Row", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 60, "target": "Lats"},
                {"name": "DB Lateral Raise", "sets": 3, "reps": "15-20", "rpe": 8.5, "rest_s": 45, "target": "Delts"}
            ],
            "ab_finisher": {"name": "Cable Woodchoppers / Rope Crunch", "travel_name": "Bicycle Crunches & Plank", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Obliques & Core"}
        },
        "Full Body": {
            "theme": "Full-Body Metabolic Hypertrophy",
            "target_groups": ["Quads", "Upper Back", "Chest", "Core Wall"],
            "objective": "Total systemic stimulation with high mechanical tension across full kinetic chain.",
            "gym_exercises": [
                {"name": "Leg Press / Hack Squat", "sets": 3, "reps": "10-12", "rpe": 8.0, "rest_s": 90, "target": "Quads"},
                {"name": "Low-Incline DB Press", "sets": 3, "reps": "8-10", "rpe": 8.0, "rest_s": 75, "target": "Chest"},
                {"name": "Chest-Supported Row", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 75, "target": "Back"},
                {"name": "Cable Lateral Raise", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Shoulders"}
            ],
            "travel_exercises": [
                {"name": "Goblet Squat", "sets": 3, "reps": "12-15", "rpe": 8.5, "rest_s": 60, "target": "Quads"},
                {"name": "Deficit Push-ups", "sets": 3, "reps": "12-15", "rpe": 8.0, "rest_s": 60, "target": "Chest"},
                {"name": "Dumbbell Row", "sets": 3, "reps": "10-12", "rpe": 8.5, "rest_s": 60, "target": "Back"}
            ],
            "ab_finisher": {"name": "Hanging Knee Raises", "travel_name": "Plank Shoulder Taps", "sets": 3, "reps": "12-15", "rpe": 9.0, "rest_s": 45, "target": "Deep Core"}
        }
    }

    split = split_type if split_type in briefing_templates else "Push"
    tmpl = briefing_templates[split]
    exercise_pool = tmpl["gym_exercises"] if is_gym else tmpl["travel_exercises"]

    filtered_exercises = []
    for ex in exercise_pool:
        if "shoulder" in joint_limitations and ("Barbell Overhead Press" in ex["name"] or "Barbell Bench" in ex["name"]):
            ex = {"name": "Neutral-Grip Dumbbell Press", "sets": ex["sets"], "reps": ex["reps"], "rpe": ex["rpe"], "rest_s": ex["rest_s"], "target": ex["target"]}
        filtered_exercises.append(ex)

    if time_minutes <= 30:
        selected_exercises = filtered_exercises[:2]
    elif time_minutes <= 45:
        selected_exercises = filtered_exercises[:3]
    else:
        selected_exercises = filtered_exercises[:4]

    ab_item = tmpl["ab_finisher"]
    ab_name = ab_item["name"] if is_gym else ab_item["travel_name"]
    if include_abs:
        selected_exercises.append({
            "name": f"🔥 Core Finisher: {ab_name}",
            "sets": 3,
            "reps": ab_item["reps"],
            "rpe": ab_item["rpe"],
            "rest_s": ab_item["rest_s"],
            "target": ab_item["target"]
        })

    if recovery_status == "DELOAD":
        for e in selected_exercises:
            e["sets"] = max(2, e["sets"] - 1)
            e["rpe"] = min(7.5, e["rpe"])

    return {
        "theme": tmpl["theme"],
        "target_groups": tmpl["target_groups"],
        "objective": tmpl["objective"],
        "environment": "Commercial Gym" if is_gym else "Home / Travel",
        "duration_min": time_minutes,
        "exercises": selected_exercises
    }

# -----------------------------------------------------------------------------
# 3. Barbell Plate Calculator
# -----------------------------------------------------------------------------
def calculate_plate_breakdown(target_weight_kg: float, bar_weight_kg: float = 20.0) -> Dict[str, Any]:
    if target_weight_kg < bar_weight_kg:
        return {"error": f"Target weight must be at least the bar weight ({bar_weight_kg} kg)."}
    
    needed_per_side = (target_weight_kg - bar_weight_kg) / 2.0
    available_plates = [25.0, 20.0, 15.0, 10.0, 5.0, 2.5, 1.25]
    
    breakdown = {}
    remaining = needed_per_side
    for plate in available_plates:
        count = int(remaining // plate)
        if count > 0:
            breakdown[f"{plate} kg"] = count
            remaining = round(remaining - (count * plate), 2)
            
    return {
        "bar_weight_kg": bar_weight_kg,
        "per_side_weight_kg": round(needed_per_side, 2),
        "plates_per_side": breakdown,
        "remainder_kg": round(remaining * 2, 2)
    }

# -----------------------------------------------------------------------------
# 4. Direct REST Barcode Lookup & Multimodal Vision Analysis
# -----------------------------------------------------------------------------
def lookup_barcode_packaged_food(barcode: str) -> Dict[str, Any]:
    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{barcode.strip()}.json"
        headers = {"User-Agent": "FitnessCoachAgent/1.0 (fitness-agent-app)"}
        resp = requests.get(url, headers=headers, timeout=5)
        
        if resp.status_code != 200:
            return {"status": "error", "message": f"Barcode {barcode} lookup failed (HTTP {resp.status_code})."}

        data = resp.json()
        if data.get("status") != 1:
            return {"status": "error", "message": f"Barcode {barcode} not found in database."}

        product = data.get("product", {})
        nutriments = product.get("nutriments", {})

        cal = nutriments.get("energy-kcal_serving") or nutriments.get("energy-kcal_100g") or nutriments.get("energy-kcal") or 0
        prot = nutriments.get("proteins_serving") or nutriments.get("proteins_100g") or nutriments.get("proteins") or 0.0
        carb = nutriments.get("carbohydrates_serving") or nutriments.get("carbohydrates_100g") or nutriments.get("carbohydrates") or 0.0
        fat = nutriments.get("fat_serving") or nutriments.get("fat_100g") or nutriments.get("fat") or 0.0

        return {
            "status": "success",
            "product_name": product.get("product_name", "Packaged Product"),
            "brand": product.get("brands", "Brand"),
            "per_serving": {
                "calories": round(float(cal)),
                "protein_g": round(float(prot), 1),
                "carbs_g": round(float(carb), 1),
                "fat_g": round(float(fat), 1),
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def analyze_meal_photo(image_file, api_key: str) -> Dict[str, Any]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = """
    You are an elite sports nutritionist. Analyze this plate photo for a fitness log:
    1. Identify all food components, portion size estimations in grams.
    2. Estimate total Calories, Protein (g), Carbohydrates (g), and Fat (g).
    3. Return ONLY a valid JSON object:
    {
      "meal_name": "string",
      "calories": int,
      "protein_g": float,
      "carbs_g": float,
      "fat_g": float,
      "breakdown": ["item 1 with grams", "item 2 with grams"]
    }
    """
    if isinstance(image_file, bytes):
        image = Image.open(io.BytesIO(image_file))
    elif hasattr(image_file, "seek"):
        image_file.seek(0)
        image = Image.open(image_file)
    else:
        image = Image.open(image_file)

    response = model.generate_content([prompt, image])
    cleaned = response.text.strip().replace("```json", "").replace("```", "")
    return json.loads(cleaned)

def parse_natural_food_or_voice(text_input: str, api_key: str) -> Dict[str, Any]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
    Analyze user input: "{text_input}"
    Determine if this is:
    A) A FOOD LOG (e.g. "200g chicken breast, 150g rice, 10g olive oil")
    B) A WORKOUT SET LOG (e.g. "Incline DB Press 28kg for 8 reps at RPE 8")

    Return ONLY a JSON object:
    If FOOD:
    {{
      "type": "food",
      "meal_type": "Breakfast" | "Lunch" | "Dinner" | "Snack" | "Post-Workout",
      "description": str,
      "calories": int,
      "protein_g": float,
      "carbs_g": float,
      "fat_g": float
    }}
    If WORKOUT:
    {{
      "type": "workout",
      "exercise_name": str,
      "weight_kg": float,
      "sets": int,
      "reps": int,
      "rpe": float
    }}
    """
    response = model.generate_content(prompt)
    cleaned = response.text.strip().replace("```json", "").replace("```", "")
    return json.loads(cleaned)

def analyze_physique_photos(image_bytes_list: List[bytes], api_key: str, user_goal: str) -> str:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    images = [Image.open(io.BytesIO(b)) for b in image_bytes_list]
    prompt = f"""
    You are an elite bodybuilding and physique assessment coach. Analyze the attached progress photo(s) for a client whose goal is: {user_goal} with an emphasis on core definition and V-taper.
    
    Provide an objective, constructive evaluation covering:
    1. **Shoulder-to-Waist Ratio & V-Taper:** Clavicular width vs pelvic line.
    2. **Core / Abdominal Wall Definition:** Visibility of rectus abdominis and obliques, estimated level of leanness.
    3. **Postural Alignment & Muscle Symmetry:** Shoulder roll, spinal neutrality.
    4. **Actionable Coaching Focus for Next 4 Weeks:** Specific hypertrophy movements or nutritional adjustments.
    
    Keep the tone professional, scholarly, and motivating.
    """
    response = model.generate_content([prompt] + images)
    return response.text

# -----------------------------------------------------------------------------
# 5. Biometric Auto-Regulation & Periodization Map
# -----------------------------------------------------------------------------
def compute_auto_regulation(sleep_hours: float, hrv_ms: float, baseline_hrv: float = 65.0) -> Dict[str, Any]:
    hrv_diff = ((hrv_ms - baseline_hrv) / baseline_hrv) * 100.0
    
    if hrv_diff < -15.0 or sleep_hours < 5.25:
        return {
            "status": "REST",
            "volume_multiplier": 0.0,
            "rpe_cap": 5.0,
            "recommendation": "High CNS / systemic fatigue. Take an active recovery walk and prioritize sleep."
        }
    elif hrv_diff < -5.0 or sleep_hours < 6.5:
        return {
            "status": "DELOAD",
            "volume_multiplier": 0.70,
            "rpe_cap": 7.5,
            "recommendation": "Elevated fatigue. Working sets reduced by 30% and intensity capped at RPE 7.5."
        }
    elif hrv_diff > 5.0 and sleep_hours >= 7.5:
        return {
            "status": "OPTIMAL",
            "volume_multiplier": 1.10,
            "rpe_cap": 9.5,
            "recommendation": "Recovery primed! Attack top sets and aim for progressive overload PRs today."
        }
    else:
        return {
            "status": "STANDARD",
            "volume_multiplier": 1.0,
            "rpe_cap": 8.5,
            "recommendation": "Baseline recovery solid. Proceed with prescribed training."
        }

def generate_six_month_macrocycle(primary_goal: str, split: str) -> List[Dict[str, Any]]:
    return [
        {
            "month": "Month 1",
            "phase": "Hypertrophy Accumulation (Base Volume)",
            "focus": "Establish baseline volume (12-14 sets/muscle), refine low-incline pressing and lat stretch.",
            "abs_focus": "Weighted cable flexion (6 sets/week) to build block thickness.",
            "intensity": "RPE 7.5 - 8.0"
        },
        {
            "month": "Month 2",
            "phase": "Progressive Overload & Density",
            "focus": "Increase load on primary compounds, introduce antagonistic supersets to elevate metabolic density.",
            "abs_focus": "Hanging leg raises + Ab wheel rollouts (8 sets/week).",
            "intensity": "RPE 8.0 - 8.5"
        },
        {
            "month": "Month 3",
            "phase": "Intensification & Peak Mechanical Tension",
            "focus": "Top-set + back-off set structure. Push 1RM progression on key lifts.",
            "abs_focus": "Heavy cable rope crunches (3-5 rep reserve).",
            "intensity": "RPE 8.5 - 9.0"
        },
        {
            "month": "Month 4",
            "phase": "Strategic Deload & Leanness Sharpening",
            "focus": "Caloric deficit tightening, drop volume by 40% in Week 1, transition to high-definition V-taper pump sets.",
            "abs_focus": "High-density core circuits + vacuum holds.",
            "intensity": "RPE 7.0 - 8.0"
        },
        {
            "month": "Month 5",
            "phase": "Peak Definition & V-Taper Specialization",
            "focus": "Lateral delt over-reaching (16 sets/week) + lat width specialization while maintaining strength.",
            "abs_focus": "Direct core 3x/week with progressive overload.",
            "intensity": "RPE 8.5 - 9.0"
        },
        {
            "month": "Month 6",
            "phase": "Physique Showcase & Functional Maintenance",
            "focus": "Consolidate new lean baseline, test estimated 1RMs, photograph final visual physique delta.",
            "abs_focus": "Maintenance volume (6 sets/week high intensity).",
            "intensity": "RPE 8.0"
        }
    ]
