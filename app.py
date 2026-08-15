import streamlit as st
import pandas as pd
import json
import base64
import time
import zxingcpp
from PIL import Image
import plotly.express as px
import plotly.graph_objects as go
import google.generativeai as genai

from state_manager import FitnessStateManager
from agent_tools import (
    calculate_true_tdee,
    calculate_tdee_and_macros,
    generate_workout_session,
    calculate_plate_breakdown,
    lookup_barcode_packaged_food,
    analyze_meal_photo,
    parse_natural_food_or_voice,
    analyze_physique_photos,
    compute_auto_regulation,
    generate_six_month_macrocycle
)

st.set_page_config(
    page_title="Personal Fitness Coach & Nutritionist",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# Custom Obsidian & Slate Styling
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    .stApp {
        background-color: #0d1117;
        color: #c9d1d9;
    }
    .metric-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .briefing-box {
        background: linear-gradient(135deg, #161b22 0%, #1f2937 100%);
        border: 1px solid #38bdf8;
        border-left: 5px solid #38bdf8;
        border-radius: 8px;
        padding: 18px;
        margin-bottom: 16px;
    }
    .badge-optimal { background-color: #064e3b; color: #34d399; padding: 4px 10px; border-radius: 12px; font-weight: 600; }
    .badge-standard { background-color: #1e3a8a; color: #60a5fa; padding: 4px 10px; border-radius: 12px; font-weight: 600; }
    .badge-deload { background-color: #78350f; color: #fbbf24; padding: 4px 10px; border-radius: 12px; font-weight: 600; }
    .badge-rest { background-color: #7f1d1d; color: #f87171; padding: 4px 10px; border-radius: 12px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Initialization & Data Fetching
# -----------------------------------------------------------------------------
API_KEY = st.secrets.get("GEMINI_API_KEY", None)
USER_ID = "usr_primary"

@st.cache_resource
def get_manager():
    return FitnessStateManager("fitness_agent.db")

state_mgr = get_manager()

try:
    context = state_mgr.get_agent_context(USER_ID)
except ValueError:
    initial_profile = {
        "user_id": USER_ID,
        "name": "Connor",
        "age": 30,
        "gender": "male",
        "height_cm": 180.0,
        "weight_kg": 78.5,
        "activity_level": "moderate",
        "primary_goal": "hypertrophy",
        "aesthetic_focus": "abs_v_taper",
        "active_split": "Push / Pull / Legs",
        "target_calories": 2600,
        "target_protein_g": 175,
        "target_carbs_g": 300,
        "target_fat_g": 70,
        "available_equipment": ["barbell", "dumbbells", "cables", "machines", "pull-up bar"],
        "dietary_restrictions": [],
        "joint_limitations": ["shoulder"]
    }
    state_mgr.upsert_user_profile(initial_profile)
    context = state_mgr.get_agent_context(USER_ID)

profile = context["profile"]
metrics = context["metrics_summary"]

# Calculate Dynamic True TDEE
true_tdee_data = calculate_true_tdee(
    metrics["recent_checkins"], 
    metrics["recent_nutrition"], 
    profile["target_calories"]
)

# -----------------------------------------------------------------------------
# Sidebar: Recovery & Quick Morning Sync
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### ⚡ **{profile['name']}**")
    st.caption(f"Goal: **{profile['primary_goal'].title()}** | Core Focus: **Abs & V-Taper**")
    
    st.markdown("---")
    st.subheader("⌚ Morning Recovery Sync")
    with st.form("biometrics_form"):
        hrv_input = st.number_input("HRV SDNN (ms)", value=65.0, step=1.0)
        rhr_input = st.number_input("Resting HR (bpm)", value=52.0, step=1.0)
        sleep_input = st.number_input("Sleep Duration (Hours)", value=7.5, step=0.25)
        weight_input = st.number_input("Today's Scale Weight (kg)", value=float(profile["weight_kg"]), step=0.1)
        
        if st.form_submit_button("Sync Recovery & Check-in", use_container_width=True):
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
            state_mgr.log_daily_weight_fatigue(USER_ID, weight_input, 3, sleep_input)
            st.success(f"Recovery Synced: {auto_reg['status']}")
            st.rerun()

    st.markdown("---")
    st.markdown(f"🔥 **True Biological TDEE:** `{true_tdee_data['true_tdee']} kcal`")
    st.caption(f"Status: {true_tdee_data['confidence']}")

# -----------------------------------------------------------------------------
# Top Recovery Banner
# -----------------------------------------------------------------------------
if metrics["today_recovery"]:
    rec = metrics["today_recovery"]
    status_map = {
        "OPTIMAL": '<span class="badge-optimal">🟢 OPTIMAL READINESS</span>',
        "STANDARD": '<span class="badge-standard">🔵 STANDARD READINESS</span>',
        "DELOAD": '<span class="badge-deload">🟡 DELOAD RECOMMENDED</span>',
        "REST": '<span class="badge-rest">🔴 REST & RECOVERY</span>'
    }
    badge_html = status_map.get(rec['readiness_status'], rec['readiness_status'])
    st.markdown(f"""
    <div class="metric-card" style="display: flex; justify-content: space-between; align-items: center;">
        <div>{badge_html} &nbsp; <b>Sleep:</b> {rec['sleep_hours']}h &nbsp;|&nbsp; <b>HRV:</b> {rec['hrv_sdnn_ms']}ms &nbsp;|&nbsp; <b>Resting HR:</b> {rec['resting_hr_bpm']} bpm</div>
        <div><b>Volume Scale:</b> {rec['volume_multiplier']}x &nbsp;|&nbsp; <b>RPE Cap:</b> {rec['rpe_cap']}</div>
    </div>
    """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 6 Main Application Tabs
# -----------------------------------------------------------------------------
tab_chat, tab_workout, tab_physique, tab_food, tab_roadmap, tab_analytics = st.tabs([
    "💬 Lead Coach Chat",
    "⏱️ Live Workout HUD",
    "📸 Physique & Visuals",
    "🥗 Food & Scanner",
    "🎯 Goals & 6-Month Plan",
    "📊 Analytics & Settings"
])

# -----------------------------------------------------------------------------
# TAB 1: Lead Coach Chat
# -----------------------------------------------------------------------------
with tab_chat:
    st.subheader("💬 Lead Fitness & Sports Nutrition Coach")
    st.caption("Chat dynamically about goal shifts, ab definition, joint tweaks, or meal suggestions.")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "content": f"Hey {profile['name']}! I have your full profile loaded (Hypertrophy + Direct Ab/V-Taper focus). How can I guide your training or nutrition today?"}
        ]

    chat_box = st.container(height=420)
    with chat_box:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    user_input = st.chat_input("Ask a question, dictate sets, or request workout adjustments...")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with chat_box:
            with st.chat_message("user"):
                st.markdown(user_input)

        if not API_KEY:
            reply = "⚠️ Please set `GEMINI_API_KEY` in Streamlit Secrets."
        else:
            genai.configure(api_key=API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            
            system_prompt = f"""
            You are the elite lead coach and sports nutritionist for {profile['name']}.
            User Stats & Goals:
            - Goal: {profile['primary_goal']} with priority on {profile['aesthetic_focus']} (deep core definition & V-taper).
            - Weight: {profile['weight_kg']} kg | Height: {profile['height_cm']} cm | Age: {profile['age']}
            - Joint Limitations: {profile['joint_limitations']} (Strictly protect these joints!)
            - True Biological TDEE: {true_tdee_data['true_tdee']} kcal | Target Intake: {profile['target_calories']} kcal ({profile['target_protein_g']}g P / {profile['target_carbs_g']}g C / {profile['target_fat_g']}g F)
            - Today's Consumed: {metrics['today_nutrition']['calories']} kcal ({metrics['today_nutrition']['protein_g']}g P)
            - Today's Recovery: {metrics['today_recovery']['readiness_status'] if metrics['today_recovery'] else 'Standard'}

            Coaching Directive:
            1. Be concise, highly actionable, evidence-based, and encouraging.
            2. Support iterative goal adjustments (e.g. accelerating fat loss, adding core density, swapping exercises).
            3. Always ensure abs and V-taper movements are programmed with heavy progressive tension.
            """
            
            response = model.generate_content([system_prompt, user_input])
            reply = response.text

        st.session_state.chat_history.append({"role": "assistant", "content": reply})
        with chat_box:
            with st.chat_message("assistant"):
                st.markdown(reply)

# -----------------------------------------------------------------------------
# TAB 2: Live In-Gym HUD & Dynamic Session Programmer
# -----------------------------------------------------------------------------
with tab_workout:
    st.subheader("🏋️ Live In-Gym HUD & Adaptive Session Programmer")
    
    col_w1, col_w2, col_w3, col_w4 = st.columns(4)
    sel_env = col_w1.selectbox("Location:", ["Commercial Gym (Full Equipment)", "Home / Travel (Dumbbells & Bands)"])
    sel_time = col_w2.selectbox("Available Time:", [45, 30, 60, 75])
    sel_split = col_w3.selectbox("Session Focus:", ["Push", "Pull", "Legs", "Upper", "Full Body"])
    include_abs_toggle = col_w4.checkbox("Include Direct Ab Finisher", value=True)

    env_code = "gym" if "Commercial" in sel_env else "travel"
    recovery_code = metrics["today_recovery"]["readiness_status"] if metrics["today_recovery"] else "STANDARD"

    session = generate_workout_session(
        time_minutes=sel_time,
        environment=env_code,
        split_type=sel_split,
        joint_limitations=profile["joint_limitations"],
        recovery_status=recovery_code,
        include_abs=include_abs_toggle
    )

    st.markdown(f"""
    <div class="briefing-box">
        <h4 style="margin: 0; color: #38bdf8;">📋 SESSION BRIEFING • {session['duration_min']} MIN • {session['environment'].upper()}</h4>
        <p style="margin-top: 8px; margin-bottom: 4px;"><b>📌 Theme:</b> {session['theme']}</p>
        <p style="margin-bottom: 4px;"><b>🎯 Target Muscle Groups:</b> {', '.join(session['target_groups'])}</p>
        <p style="margin-bottom: 4px;"><b>🎯 Mechanical Objective:</b> {session['objective']}</p>
        <p style="margin-bottom: 0;"><b>🩹 Joint Guards:</b> {', '.join(profile['joint_limitations']) if profile['joint_limitations'] else 'None (Full ROM)'}</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### 📝 Prescribed Exercise Sequence")
    for idx, ex in enumerate(session["exercises"]):
        with st.expander(f"**#{idx+1}: {ex['name']}** — {ex['sets']} sets × {ex['reps']} (Target: {ex['target']})", expanded=(idx==0)):
            last_perf = state_mgr.get_last_performance_for_exercise(USER_ID, ex["name"])
            if last_perf:
                st.info(f"👻 **Previous Session Performance:** {last_perf['reps']} reps @ {last_perf['weight_kg']} kg (RPE {last_perf.get('rpe', 8.0)})")
            else:
                st.caption("No historical log for this exercise yet. Establish baseline load.")

            c_log1, c_log2, c_log3, c_log4 = st.columns(4)
            w_val = c_log1.number_input(f"Weight (kg) - #{idx+1}", value=24.0, step=0.5, key=f"w_{idx}")
            r_val = c_log2.number_input(f"Reps - #{idx+1}", value=10, step=1, key=f"r_{idx}")
            rpe_val = c_log3.slider(f"RPE - #{idx+1}", 5.0, 10.0, 8.0, 0.5, key=f"rpe_{idx}")
            rir_val = c_log4.slider(f"RIR - #{idx+1}", 0, 5, 2, key=f"rir_{idx}")

            c_act1, c_act2 = st.columns(2)
            if c_act1.button(f"✅ Log Working Set", key=f"btn_log_{idx}", use_container_width=True):
                state_mgr.log_workout_exercise(
                    USER_ID, session["theme"], ex["name"], 1, int(r_val), float(w_val), float(rpe_val), float(rir_val)
                )
                st.success(f"Logged {ex['name']}: {r_val} reps @ {w_val} kg!")
                st.rerun()

            if "Barbell" in ex["name"] or "Press" in ex["name"]:
                with st.popover(f"⚖️ Plate Calc for {w_val} kg"):
                    pb = calculate_plate_breakdown(float(w_val))
                    if "error" in pb:
                        st.error(pb["error"])
                    else:
                        st.write(f"**Bar:** {pb['bar_weight_kg']} kg | **Per Side:** {pb['per_side_weight_kg']} kg")
                        for p, cnt in pb["plates_per_side"].items():
                            st.write(f"- {cnt}x {p}")

    st.markdown("---")
    st.subheader("⏱️ In-Gym Rest Timer")
    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    if t_col1.button("⏱️ Rest 60s", use_container_width=True):
        st.toast("Rest Timer Started: 60s")
    if t_col2.button("⏱️ Rest 90s", use_container_width=True):
        st.toast("Rest Timer Started: 90s")
    if t_col3.button("⏱️ Rest 120s", use_container_width=True):
        st.toast("Rest Timer Started: 120s")
    if t_col4.button("⏱️ Rest 180s", use_container_width=True):
        st.toast("Rest Timer Started: 180s")

# -----------------------------------------------------------------------------
# TAB 3: Physique & Visual Progress Tracker
# -----------------------------------------------------------------------------
with tab_physique:
    st.subheader("📸 Weekly Visual Progress & AI Physique Analysis")
    st.caption("Upload weekly progress photos (Front, Side, Back) to track muscle shape, V-taper, and core definition.")

    with st.form("physique_upload_form"):
        p_pose = st.selectbox("Pose Type:", ["Front Relaxed", "Front Double Bicep", "Side Profile", "Back Double Bicep"])
        p_file = st.file_uploader("Upload Weekly Photo", type=["jpg", "jpeg", "png"])
        p_submit = st.form_submit_button("Inspect & Save Photo", use_container_width=True)

        if p_submit and p_file:
            photo_bytes = p_file.read()
            with st.spinner("AI evaluating muscle definition & V-taper..."):
                feedback = analyze_physique_photos([photo_bytes], API_KEY, f"{profile['primary_goal']} with emphasis on abs and V-taper")
                state_mgr.log_physique_photo(USER_ID, p_pose, photo_bytes, feedback)
                st.success("Physique photo and AI evaluation saved!")
                st.rerun()

    st.markdown("---")
    st.subheader("🖼️ Historical Progress Gallery")
    photos = state_mgr.get_physique_photos(USER_ID)
    if photos:
        for p in photos:
            with st.container():
                col_img, col_fb = st.columns([1, 2])
                img_data = base64.b64decode(p["photo_base64"])
                col_img.image(img_data, caption=f"{p['log_date']} • {p['pose']}", use_container_width=True)
                col_fb.markdown(f"**AI Physique Feedback ({p['log_date']}):**")
                col_fb.info(p["ai_feedback"])
                st.markdown("---")
    else:
        st.info("No physique photos uploaded yet. Upload your baseline photo above!")

# -----------------------------------------------------------------------------
# TAB 4: Food & Scanner
# -----------------------------------------------------------------------------
with tab_food:
    st.subheader("🥗 Smart Nutrition & Macro Tracker")
    nutr = metrics["today_nutrition"]
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Calories", f"{nutr['calories']} / {profile['target_calories']} kcal", delta=f"{profile['target_calories'] - nutr['calories']} left")
    col_m2.metric("Protein", f"{nutr['protein_g']} / {profile['target_protein_g']} g")
    col_m3.metric("Carbs", f"{nutr['carbs_g']} / {profile['target_carbs_g']} g")
    col_m4.metric("Fat", f"{nutr['fat_g']} / {profile['target_fat_g']} g")

    st.markdown("---")
    log_opt = st.radio("Logging Method:", ["Natural Text / Voice Dictation", "Barcode Scanner", "Plate Photo Vision", "Staple Presets"], horizontal=True)

    if log_opt == "Natural Text / Voice Dictation":
        food_txt = st.text_input("Describe your meal (e.g. '200g grilled salmon, 150g quinoa, 10g olive oil'):")
        if st.button("Parse & Log Meal", use_container_width=True) and food_txt and API_KEY:
            with st.spinner("Analyzing macros..."):
                res = parse_natural_food_or_voice(food_txt, API_KEY)
                if res.get("type") == "food":
                    state_mgr.log_nutrition_item(
                        USER_ID, res["description"], res["calories"], res["protein_g"], res["carbs_g"], res["fat_g"], res.get("meal_type", "General")
                    )
                    st.success(f"Logged: {res['description']} ({res['calories']} kcal, {res['protein_g']}g P)")
                    st.rerun()

    elif log_opt == "Barcode Scanner":
        bc_input = st.text_input("Enter Barcode Number (or use camera below):")
        bc_cam = st.camera_input("Scan Barcode")
        scanned_code = bc_input
        if bc_cam:
            img = Image.open(bc_cam)
            codes = zxingcpp.read_barcodes(img)
            if codes:
                scanned_code = codes[0].text
        
        if scanned_code:
            st.success(f"Barcode: {scanned_code}")
            b_data = lookup_barcode_packaged_food(scanned_code)
            if b_data.get("status") == "success":
                ps = b_data["per_serving"]
                st.write(f"**{b_data['product_name']}** ({b_data['brand']})")
                st.write(f"Calories: {ps['calories']} kcal | Protein: {ps['protein_g']}g | Carbs: {ps['carbs_g']}g | Fat: {ps['fat_g']}g")
                if st.button("Add to Today's Log", use_container_width=True):
                    state_mgr.log_nutrition_item(USER_ID, b_data['product_name'], ps['calories'], ps['protein_g'], ps['carbs_g'], ps['fat_g'])
                    st.success("Item logged!")
                    st.rerun()

    elif log_opt == "Plate Photo Vision":
        p_plate = st.file_uploader("Upload Plate Photo", type=["jpg", "png", "jpeg"]) or st.camera_input("Snap Plate")
        if p_plate and API_KEY:
            if st.button("Estimate Portion Macros with Gemini Vision", use_container_width=True):
                with st.spinner("Analyzing plate..."):
                    res = analyze_meal_photo(p_plate, API_KEY)
                    st.write(f"**Meal:** {res['meal_name']}")
                    st.write(f"Calories: {res['calories']} kcal | Protein: {res['protein_g']}g | Carbs: {res['carbs_g']}g | Fat: {res['fat_g']}g")
                    st.write(f"Components: {', '.join(res.get('breakdown', []))}")
                    if st.button("Save Plate to Diary", use_container_width=True):
                        state_mgr.log_nutrition_item(USER_ID, res['meal_name'], res['calories'], res['protein_g'], res['carbs_g'], res['fat_g'])
                        st.success("Plate logged!")
                        st.rerun()

    elif log_opt == "Staple Presets":
        presets = [
            {"name": "Post-Workout Whey & Cream of Rice", "cal": 420, "p": 50.0, "c": 50.0, "f": 2.0},
            {"name": "Chicken Breast (200g) & Jasmine Rice (200g)", "cal": 550, "p": 62.0, "c": 58.0, "f": 4.0},
            {"name": "0% Greek Yogurt (300g) + Berries (100g)", "cal": 240, "p": 32.0, "c": 22.0, "f": 0.5},
            {"name": "4 Whole Eggs + Sourdough Toast (2 slices)", "cal": 480, "p": 28.0, "c": 36.0, "f": 22.0}
        ]
        for p in presets:
            col_pr1, col_pr2 = st.columns([3, 1])
            col_pr1.write(f"**{p['name']}** — {p['cal']} kcal ({p['p']}g P / {p['c']}g C / {p['f']}g F)")
            if col_pr2.button("⚡ Quick Log", key=f"pr_{p['name']}", use_container_width=True):
                state_mgr.log_nutrition_item(USER_ID, p['name'], p['cal'], p['p'], p['c'], p['f'], "Staple")
                st.success(f"Logged {p['name']}!")
                st.rerun()

# -----------------------------------------------------------------------------
# TAB 5: Goals & 6-Month Macrocycle Plan
# -----------------------------------------------------------------------------
with tab_roadmap:
    st.subheader("🎯 6-Month Macrocycle Periodization Plan")
    st.caption("Structured progression map tailored for progressive overload, V-taper aesthetics, and deep abdominal hypertrophy.")

    roadmap = generate_six_month_macrocycle(profile["primary_goal"], profile.get("active_split", "Push / Pull / Legs"))
    for block in roadmap:
        with st.container():
            st.markdown(f"""
            <div class="metric-card">
                <h4 style="margin: 0; color: #38bdf8;">{block['month']}: {block['phase']}</h4>
                <p style="margin-top: 6px; margin-bottom: 4px;"><b>🏋️ Focus:</b> {block['focus']}</p>
                <p style="margin-bottom: 4px;"><b>🔥 Core / Abs Protocol:</b> {block['abs_focus']}</p>
                <p style="margin-bottom: 0;"><b>🎯 Intensity Target:</b> <code>{block['intensity']}</code></p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🏆 All-Time PR Trophy Case (Estimated 1RMs)")
    prs = metrics["personal_records"]
    if prs:
        df_pr = pd.DataFrame(prs)
        st.dataframe(df_pr[["exercise_name", "weight_kg", "reps", "est_1rm", "achieved_date"]], use_container_width=True)
    else:
        st.info("Log heavy working sets in the Live Workout HUD to populate your PR trophy case.")

# -----------------------------------------------------------------------------
# TAB 6: Analytics, Habits & Database Settings
# -----------------------------------------------------------------------------
with tab_analytics:
    st.subheader("📊 Daily Longevity Habits & Micro-Checklist")
    
    habits = state_mgr.get_daily_habits(USER_ID)
    with st.form("habits_form"):
        col_h1, col_h2, col_h3 = st.columns(3)
        h_creatine = col_h1.checkbox("💊 5g Creatine Monohydrate", value=bool(habits.get("creatine", 0)))
        h_water = col_h2.checkbox("💧 3.0L Water Target", value=bool(habits.get("water_target", 0)))
        h_steps = col_h3.checkbox("🚶 8,000+ Daily Steps", value=bool(habits.get("steps_8k", 0)))
        
        col_h4, col_h5, _ = st.columns(3)
        h_sleep = col_h4.checkbox("😴 7.5h+ Sleep Target", value=bool(habits.get("sleep_target", 0)))
        h_weight = col_h5.checkbox("⚖️ Morning Weigh-In", value=bool(habits.get("scale_weight", 0)))

        if st.form_submit_button("Save Habits Status", use_container_width=True):
            state_mgr.log_daily_habits(USER_ID, int(h_creatine), int(h_water), int(h_steps), int(h_sleep), int(h_weight))
            st.success("Habits logged!")
            st.rerun()

    st.markdown("---")
    st.subheader("📈 Bodyweight Trajectory (14-Day Rolling)")
    checkins = metrics["recent_checkins"]
    if checkins:
        df_chk = pd.DataFrame(checkins)
        fig_weight = px.line(df_chk, x="log_date", y="weight_kg", title="Scale Weight Trend (kg)", markers=True)
        fig_weight.update_layout(template="plotly_dark", paper_bgcolor="#161b22", plot_bgcolor="#161b22")
        st.plotly_chart(fig_weight, use_container_width=True)

    st.markdown("---")
    st.subheader("⚙️ Edit Profile & Health Constraints")
    with st.form("profile_edit_form"):
        col_p1, col_p2, col_p3 = st.columns(3)
        p_name = col_p1.text_input("Name", value=profile["name"])
        p_age = col_p2.number_input("Age", value=int(profile["age"]))
        p_gender = col_p3.selectbox("Gender", ["male", "female"], index=0 if profile["gender"] == "male" else 1)
        
        col_p4, col_p5, col_p6 = st.columns(3)
        p_weight = col_p4.number_input("Weight (kg)", value=float(profile["weight_kg"]), step=0.1)
        p_height = col_p5.number_input("Height (cm)", value=float(profile["height_cm"]), step=0.5)
        p_act = col_p6.selectbox("Activity Level", ["sedentary", "light", "moderate", "very_active", "extra_active"], index=2)
        
        p_joints = st.multiselect("Joint Constraints (Leave empty if pain-free):", ["shoulder", "knee", "lower_back", "elbow", "wrist"], default=profile["joint_limitations"])
        
        if st.form_submit_button("Update Profile & Recalculate Macros", use_container_width=True):
            new_macros = calculate_tdee_and_macros(p_weight, p_height, p_age, p_gender, p_act, profile["primary_goal"])
            updated = {
                "user_id": USER_ID,
                "name": p_name,
                "age": p_age,
                "gender": p_gender,
                "height_cm": p_height,
                "weight_kg": p_weight,
                "activity_level": p_act,
                "primary_goal": profile["primary_goal"],
                "aesthetic_focus": profile.get("aesthetic_focus", "abs_v_taper"),
                "active_split": profile.get("active_split", "Push / Pull / Legs"),
                "target_calories": new_macros["target_calories"],
                "target_protein_g": new_macros["protein_g"],
                "target_carbs_g": new_macros["carb_g"],
                "target_fat_g": new_macros["fat_g"],
                "available_equipment": profile["available_equipment"],
                "dietary_restrictions": profile["dietary_restrictions"],
                "joint_limitations": p_joints
            }
            state_mgr.upsert_user_profile(updated)
            st.success("Profile updated!")
            st.rerun()

    st.markdown("---")
    st.subheader("💾 Cloud Database Backup")
    json_backup = state_mgr.export_all_data_json(USER_ID)
    st.download_button(
        label="📥 Download Full Database Backup (JSON)",
        data=json_backup,
        file_name="fitness_agent_backup.json",
        mime="application/json",
        use_container_width=True
    )
