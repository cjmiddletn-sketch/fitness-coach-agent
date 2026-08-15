import os
import json
import requests
from typing import Dict, List, Any, Optional
from PIL import Image
import google.generativeai as genai
from openfoodfacts import API, APIVersion, Country, Environment, Flavor

# -----------------------------------------------------------------------------
# 1. Deterministic Math & Macro Calculations
# -----------------------------------------------------------------------------
def calculate_tdee_and_macros(
    weight_kg: float,
    height_cm: float,
    age: int,
    gender: str,
    activity_level: str,
    goal: str
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
    tdee = bmr * multipliers.get(activity_level.lower(), 1.2)

    if goal == "fat_loss":
        target_calories = tdee - 500
    elif goal == "muscle_gain":
        target_calories = tdee + 300
    else:
        target_calories = tdee

    min_floor = 1500 if gender.lower() == "male" else 1200
    if target_calories < min_floor:
        target_calories = min_floor

    protein_g = round(2.0 * weight_kg)
    fat_calories = target_calories * 0.25
    fat_g = round(fat_calories / 9)
    carb_calories = target_calories - ((protein_g * 4) + fat_calories)
    carb_g = max(0, round(carb_calories / 4))

    return {
        "bmr": round(bmr, 1),
        "tdee": round(tdee, 1),
        "target_calories": round(target_calories),
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carb_g": carb_g
    }

# -----------------------------------------------------------------------------
# 2. Exercise Substitutions & Volume
# -----------------------------------------------------------------------------
def suggest_exercise_substitutions(
    target_muscle: str, 
    available_equipment: List[str], 
    joint_limitations: List[str]
) -> List[Dict[str, str]]:
    exercise_db = [
        {"name": "Barbell Bench Press", "muscle": "chest", "equipment": "barbell", "stress_joints": ["shoulder", "wrist"]},
        {"name": "Dumbbell Low Incline Press", "muscle": "chest", "equipment": "dumbbells", "stress_joints": ["wrist"]},
        {"name": "Push-ups", "muscle": "chest", "equipment": "bodyweight", "stress_joints": ["wrist"]},
        {"name": "Goblet Squat", "muscle": "quads", "equipment": "dumbbells", "stress_joints": ["knee"]},
        {"name": "Barbell Back Squat", "muscle": "quads", "equipment": "barbell", "stress_joints": ["knee", "lower_back"]},
        {"name": "Pull-ups", "muscle": "back", "equipment": "pull-up bar", "stress_joints": ["shoulder", "elbow"]},
        {"name": "Dumbbell Single-Arm Row", "muscle": "back", "equipment": "dumbbells", "stress_joints": []},
        {"name": "Romanian Deadlift", "muscle": "hamstrings", "equipment": "dumbbells", "stress_joints": ["lower_back"]},
    ]
    
    suitable = []
    for ex in exercise_db:
        if ex["muscle"].lower() != target_muscle.lower():
            continue
        if ex["equipment"] not in available_equipment and ex["equipment"] != "bodyweight":
            continue
        if any(joint in joint_limitations for joint in ex["stress_joints"]):
            continue
        suitable.append({"exercise": ex["name"], "equipment": ex["equipment"]})
    return suitable

# -----------------------------------------------------------------------------
# 3. Barcode & Multimodal Vision Meal Analysis
# -----------------------------------------------------------------------------
def lookup_barcode_packaged_food(barcode: str) -> Dict[str, Any]:
    api = API(
        user_agent="FitnessAgent/1.0",
        country=Country.world,
        flavor=Flavor.off,
        version=APIVersion.v2,
        environment=Environment.org
    )
    try:
        product_data = api.product.get(barcode)
        if not product_data or product_data.get("status") != 1:
            return {"status": "error", "message": f"Barcode {barcode} not found."}

        product = product_data.get("product", {})
        nutriments = product.get("nutriments", {})

        return {
            "status": "success",
            "product_name": product.get("product_name", "Packaged Food"),
            "brand": product.get("brands", "Brand"),
            "per_serving": {
                "calories": round(nutriments.get("energy-kcal_serving", nutriments.get("energy-kcal_100g", 0))),
                "protein_g": round(nutriments.get("proteins_serving", nutriments.get("proteins_100g", 0)), 1),
                "carbs_g": round(nutriments.get("carbohydrates_serving", nutriments.get("carbohydrates_100g", 0)), 1),
                "fat_g": round(nutriments.get("fat_serving", nutriments.get("fat_100g", 0)), 1),
            }
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def analyze_meal_photo(image_file, api_key: str) -> Dict[str, Any]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = """
    Analyze this meal photo for a sports nutrition log.
    1. Identify each food item and estimate weight/portions.
    2. Estimate total Calories, Protein (g), Carbohydrates (g), and Fat (g).
    3. Return ONLY a valid JSON object with keys:
       "meal_name": str,
       "calories": int,
       "protein_g": float,
       "carbs_g": float,
       "fat_g": float,
       "breakdown": list of strings
    """
    image = Image.open(image_file)
    response = model.generate_content([prompt, image])
    cleaned = response.text.strip().replace("```json", "").replace("```", "")
    return json.loads(cleaned)

def parse_natural_food_or_voice(text_input: str, api_key: str) -> Dict[str, Any]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    
    prompt = f"""
    Analyze this user query: "{text_input}"
    Determine if this is:
    A) A FOOD LOG (e.g. "2 eggs, sourdough toast, black coffee")
    B) A WORKOUT SET LOG (e.g. "DB Press 28kg for 8 reps RPE 8")
    
    Return ONLY a valid JSON object.
    If FOOD:
    {{
      "type": "food",
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

# -----------------------------------------------------------------------------
# 4. Biometric Auto-Regulation Engine
# -----------------------------------------------------------------------------
def compute_auto_regulation(sleep_hours: float, hrv_ms: float, baseline_hrv: float = 60.0) -> Dict[str, Any]:
    hrv_diff = ((hrv_ms - baseline_hrv) / baseline_hrv) * 100.0
    
    if hrv_diff < -15.0 or sleep_hours < 5.0:
        return {
            "status": "REST",
            "volume_multiplier": 0.0,
            "rpe_cap": 5.0,
            "recommendation": "High systemic fatigue detected. Focus on active recovery and sleep tonight."
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
            "recommendation": "Recovery is prime! Push progressive overload on your top sets today."
        }
    else:
        return {
            "status": "STANDARD",
            "volume_multiplier": 1.0,
            "rpe_cap": 8.5,
            "recommendation": "Recovery baseline is solid. Proceed with prescribed training."
        }
