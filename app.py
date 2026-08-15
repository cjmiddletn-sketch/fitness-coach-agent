import streamlit as st
import pandas as pd
import json
import zxingcpp
from PIL import Image
import google.generativeai as genai

from state_manager import FitnessStateManager
from agent_tools import (
    calculate_tdee_and_macros,
    suggest_exercise_substitutions,
    lookup_barcode_packaged_food,
    analyze_meal_photo,
    parse_natural_food_or_voice,
    compute_auto_regulation
)

st.set_page_config(page_title="AI Fitness Coach & Nutritionist", page_icon="🏋️‍♂️", layout="wide")

# -----------------------------------------------------------------------------
# 1. API Keys & State Initialization
# -----------------------------------------------------------------------------
API_KEY = st.secrets.get("GEMINI_API_KEY", None)
USER_ID = "usr_primary"

@st.cache_resource
def get_manager():
    return FitnessStateManager("fitness_agent.db")

state_mgr = get_manager()

# Ensure default profile exists
try:
    context = state_mgr.get_agent_context(USER_ID)
except ValueError:
    initial_profile = {
        "user_id": USER_ID,
        "name": "Connor",
        "age": 30,
        "gender": "male",
        "height_cm": 180,
        "weight_kg": 78.5,
        "activity_level": "moderate",
        "primary_goal": "hypertrophy",
        "target_calories": 2600,
        "target_protein_g": 165,
        "target_carbs_g": 310,
        "target_fat_g": 72,
        "available_equipment": ["dumbbells", "pull-up bar", "barbell"],
        "dietary_restrictions": ["lactose_intolerant"],
        "joint_limitations": ["shoulder"]
    }
    state_mgr.upsert_user_profile(initial_profile)
    context = state_mgr.get_agent_context(USER_ID)

profile = context["profile"]
metrics = context["metrics_summary"]

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": f"Hey {profile['name']}! Ready to train. What are we hitting today, or what would you like to log?"}
    ]

# -----------------------------------------------------------------------------
# 2. Sidebar: Quick Logger & Profile Context
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Profile & Constraints")
    st.write(f"**Goal:** {profile['primary_goal'].title()}")
    st.write(f"**Weight:** {profile['weight_kg']} kg | **Height:** {profile['height_cm']} cm")
    st.write(f"**Equipment:** {', '.join(profile['available_equipment'])}")
    st.write(f"**Injuries/Limitations:** {', '.join(profile['joint_limitations'])}")
    
    st.divider()
    st.subheader("⌚ Apple Watch / Morning Sync")
    with st.form("biometrics_form"):
        hrv_input = st.number_input("HRV SDNN (ms)", value=65.0, step=1.0)
        rhr_input = st.number_input("Resting HR (bpm)", value=52.0, step=1.0)
        sleep_input = st.number_input("Sleep Duration (Hours)", value=7.5, step=0.25)
        
        if st.form_submit_button("Sync Biometrics"):
            auto_reg = compute_auto_regulation(sleep_input, hrv_input)
            state_mgr.log_recovery_biometrics(
                user_id=USER_ID,
                hrv_ms=hrv_input,
                resting_hr=rhr_input,
                sleep_hours=sleep_input,
                status=auto_reg["status"],
                volume_mult=auto_reg["volume_multiplier"],
                rpe_cap=auto_reg["rpe_cap"]
            )
            state_mgr.log_daily_weight_fatigue(USER_ID, profile["weight_kg"], 4, sleep_input)
            st.success(f"Recovery logged: {auto_reg['status']}")
            st.rerun()

# -----------------------------------------------------------------------------
# 3. Main Dashboard & Chat Layout
# -----------------------------------------------------------------------------
st.title("🏋️ Personal Fitness Coach & Nutritionist")

# Recovery Status Banner
if metrics["today_recovery"]:
    rec = metrics["today_recovery"]
    status_colors = {"OPTIMAL": "🟢", "STANDARD": "🔵", "DELOAD": "🟡", "REST": "🔴"}
    st.info(f"{status_colors.get(rec['readiness_status'], '⚪')} **Today's Readiness:** {rec['readiness_status']} | Volume Multiplier: {rec['volume_multiplier']}x | RPE Cap: {rec['rpe_cap']}")

chat_tab, food_tab, workout_tab, analytics_tab = st.tabs(["💬 Lead Coach Chat", "🥗 Food & Barcode Log", "🏋️ Workout Log", "📊 Analytics Dashboard"])

# -----------------------------------------------------------------------------
# TAB 1: Chat Interface with Lead Coach
# -----------------------------------------------------------------------------
with chat_tab:
    chat_container = st.container(height=450)
    with chat_container:
        for m in st.session_state.messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

    if user_prompt := st.chat_input("Ask advice, dictate sets, or ask for meal substitutions..."):
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_prompt)

        if not API_KEY:
            bot_reply = "⚠️ Please configure your `GEMINI_API_KEY` in Streamlit Secrets."
        else:
            genai.configure(api_key=API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            system_prompt = f"""
            You are the elite Lead Fitness Coach and Sports Nutritionist for {profile['name']}.
            User Baseline:
            - Goal: {profile['primary_goal']}
            - Weight: {profile['weight_kg']}kg, Height: {profile['height_cm']}cm
            - Equipment: {profile['available_equipment']}
            - Injury/Joint limitations: {profile['joint_limitations']}
            - Dietary: {profile['dietary_restrictions']}
            - Current Target Calories: {profile['target_calories']} kcal ({profile['target_protein_g']}g P / {profile['target_carbs_g']}g C / {profile['target_fat_g']}g F)
            - Today's Consumed: {metrics['today_nutrition']['calories']} kcal ({metrics['today_nutrition']['protein_g']}g P)
            - Recovery Status: {metrics['today_recovery']['readiness_status'] if metrics['today_recovery'] else 'Normal'}

            Answer concisely, directly, and with actionable strength and nutrition coaching advice.
            """
            
            response = model.generate_content([system_prompt, user_prompt])
            bot_reply = response.text

        st.session_state.messages.append({"role": "assistant", "content": bot_reply})
        with chat_container:
            with st.chat_message("assistant"):
                st.markdown(bot_reply)

# -----------------------------------------------------------------------------
# TAB 2: Food & Barcode / Meal Photo Logger
# -----------------------------------------------------------------------------
with food_tab:
    st.subheader("📸 Log Meals via Photo, Barcode, or Text")
    log_mode = st.radio("Select Input Mode:", ["Text / Voice Description", "Scan Barcode", "Upload Meal Photo"], horizontal=True)

    if log_mode == "Text / Voice Description":
        food_text = st.text_input("Describe your meal (e.g., '150g grilled chicken, 200g jasmine rice, 1 avocado'):")
        if st.button("Analyze & Log Food") and food_text and API_KEY:
            with st.spinner("Analyzing nutrition..."):
                parsed = parse_natural_food_or_voice(food_text, API_KEY)
                if parsed.get("type") == "food":
                    state_mgr.log_nutrition_item(
                        USER_ID, parsed["description"], parsed["calories"], 
                        parsed["protein_g"], parsed["carbs_g"], parsed["fat_g"]
                    )
                    st.success(f"Logged: {parsed['description']} ({parsed['calories']} kcal, {parsed['protein_g']}g Protein)")
                    st.rerun()

    elif log_mode == "Scan Barcode":
        barcode_img = st.camera_input("Scan Barcode with Camera")
        if barcode_img:
            image = Image.open(barcode_img)
            barcodes = zxingcpp.read_barcodes(image)
            if barcodes:
                code_str = barcodes[0].text
                st.success(f"Barcode Found: {code_str}")
                data = lookup_barcode_packaged_food(code_str)
                if data["status"] == "success":
                    p = data["per_serving"]
                    st.write(f"**{data['product_name']}** ({data['brand']})")
                    st.write(f"Calories: {p['calories']} kcal | Protein: {p['protein_g']}g | Carbs: {p['carbs_g']}g | Fat: {p['fat_g']}g")
                    if st.button("Confirm & Add to Diary"):
                        state_mgr.log_nutrition_item(USER_ID, data['product_name'], p['calories'], p['protein_g'], p['carbs_g'], p['fat_g'])
                        st.success("Added!")
                        st.rerun()
            else:
                st.warning("No barcode detected. Align camera closer with good lighting.")

    elif log_mode == "Upload Meal Photo":
        meal_file = st.file_uploader("Upload Plate Photo", type=["jpg", "png", "jpeg"]) or st.camera_input("Snap Plate Photo")
        if meal_file and API_KEY:
            if st.button("Analyze Plate with Gemini Vision"):
                with st.spinner("Calculating portion sizes and macros..."):
                    result = analyze_meal_photo(meal_file, API_KEY)
                    st.write(f"**Identified:** {result['meal_name']}")
                    st.write(f"**Calories:** {result['calories']} kcal | **Protein:** {result['protein_g']}g | **Carbs:** {result['carbs_g']}g | **Fat:** {result['fat_g']}g")
                    st.write("**Components:**", ", ".join(result.get("breakdown", [])))
                    if st.button("Confirm and Save Meal"):
                        state_mgr.log_nutrition_item(USER_ID, result['meal_name'], result['calories'], result['protein_g'], result['carbs_g'], result['fat_g'])
                        st.success("Meal saved to diary!")
                        st.rerun()

# -----------------------------------------------------------------------------
# TAB 3: Quick Workout Logger (In-Gym)
# -----------------------------------------------------------------------------
with workout_tab:
    st.subheader("🏋️ Live Set Logger")
    col1, col2, col3, col4 = st.columns(4)
    ex_name = col1.text_input("Exercise", value="Dumbbell Incline Press")
    ex_weight = col2.number_input("Weight (kg)", value=24.0, step=1.0)
    ex_reps = col3.number_input("Reps", value=10, step=1)
    ex_rpe = col4.slider("RPE", 5.0, 10.0, 8.0, 0.5)

    if st.button("Log Working Set"):
        state_mgr.log_workout_exercise(USER_ID, ex_name, 1, int(ex_reps), ex_weight, ex_rpe)
        st.success(f"Logged: 1 Set x {ex_reps} reps @ {ex_weight}kg (RPE {ex_rpe})")
        st.rerun()

    st.divider()
    st.subheader("Recent Sets Today")
    workouts = metrics["recent_workouts"]
    if workouts:
        df_w = pd.DataFrame(workouts)
        st.dataframe(df_w[["log_date", "exercise_name", "reps", "weight_kg", "rpe"]], use_container_width=True)

# -----------------------------------------------------------------------------
# TAB 4: Analytics Dashboard
# -----------------------------------------------------------------------------
with analytics_tab:
    st.subheader("🎯 Daily Macro Allocation vs Consumed")
    nutr = metrics["today_nutrition"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Calories", f"{nutr['calories']} / {profile['target_calories']} kcal", delta=f"{profile['target_calories'] - nutr['calories']} remaining")
    c2.metric("Protein", f"{nutr['protein_g']} / {profile['target_protein_g']} g")
    c3.metric("Carbs", f"{nutr['carbs_g']} / {profile['target_carbs_g']} g")
    c4.metric("Fat", f"{nutr['fat_g']} / {profile['target_fat_g']} g")
    
    st.divider()
    st.subheader("📈 Bodyweight & Check-in History")
    checkins = metrics["recent_checkins"]
    if checkins:
        df_c = pd.DataFrame(checkins)
        st.line_chart(df_c.set_index("log_date")["weight_kg"])
    else:
        st.info("No check-in history logged yet.")
