import json
import sqlite3
import base64
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

class FitnessStateManager:
    def __init__(self, db_path: str = "fitness_agent.db"):
        self.db_path = db_path
        self._init_db()
        self._migrate_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. User Profile Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users_profile (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT NOT NULL,
                height_cm REAL NOT NULL,
                weight_kg REAL NOT NULL,
                activity_level TEXT NOT NULL,
                primary_goal TEXT NOT NULL,
                aesthetic_focus TEXT NOT NULL DEFAULT 'abs_v_taper',
                active_split TEXT NOT NULL DEFAULT 'Push / Pull / Legs',
                target_calories INTEGER NOT NULL,
                target_protein_g INTEGER NOT NULL,
                target_carbs_g INTEGER NOT NULL,
                target_fat_g INTEGER NOT NULL,
                available_equipment TEXT NOT NULL DEFAULT '[]',
                dietary_restrictions TEXT NOT NULL DEFAULT '[]',
                joint_limitations TEXT NOT NULL DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. Daily Nutrition Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS nutrition_daily_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                meal_type TEXT DEFAULT 'General',
                food_description TEXT,
                actual_calories INTEGER NOT NULL,
                actual_protein_g REAL NOT NULL,
                actual_carbs_g REAL NOT NULL,
                actual_fat_g REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE
            );
            """)

            # 3. Workout Plan Logs Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS workout_plan_logs (
                workout_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                session_theme TEXT,
                exercise_name TEXT NOT NULL,
                sets INTEGER NOT NULL,
                reps INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                rpe REAL,
                rir REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE
            );
            """)

            # 4. Weight & Check-in Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS weight_fatigue_logs (
                checkin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                weight_kg REAL NOT NULL,
                fatigue_score INTEGER,
                sleep_hours REAL,
                notes TEXT,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE,
                UNIQUE(user_id, log_date)
            );
            """)

            # 5. Recovery Biometrics Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS recovery_biometrics (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                hrv_sdnn_ms REAL,
                resting_hr_bpm REAL,
                sleep_hours REAL,
                readiness_status TEXT,
                volume_multiplier REAL DEFAULT 1.0,
                rpe_cap REAL DEFAULT 10.0,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE,
                UNIQUE(user_id, log_date)
            );
            """)

            # 6. Physique Photos Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS physique_photos (
                photo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                pose TEXT NOT NULL,
                photo_base64 TEXT NOT NULL,
                ai_feedback TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE
            );
            """)

            # 7. Daily Habits Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_habits (
                habit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                creatine INTEGER DEFAULT 0,
                water_target INTEGER DEFAULT 0,
                steps_8k INTEGER DEFAULT 0,
                sleep_target INTEGER DEFAULT 0,
                scale_weight INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE,
                UNIQUE(user_id, log_date)
            );
            """)

            # 8. Muscle Soreness Feedback Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS muscle_soreness_pump (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                muscle_group TEXT NOT NULL,
                soreness_rating INTEGER,
                pump_rating INTEGER,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE
            );
            """)

            # 9. Personal Records Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS personal_records (
                pr_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                exercise_name TEXT NOT NULL,
                weight_kg REAL NOT NULL,
                reps INTEGER NOT NULL,
                est_1rm REAL NOT NULL,
                achieved_date DATE NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE,
                UNIQUE(user_id, exercise_name)
            );
            """)
            conn.commit()

    def _migrate_db(self):
        """Auto-migrates existing tables to add any missing columns non-destructively."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Helper to get existing column names for a table
            def get_columns(table_name):
                cursor.execute(f"PRAGMA table_info({table_name})")
                return [row["name"] for row in cursor.fetchall()]

            # 1. users_profile migration
            cols = get_columns("users_profile")
            if "aesthetic_focus" not in cols:
                cursor.execute("ALTER TABLE users_profile ADD COLUMN aesthetic_focus TEXT NOT NULL DEFAULT 'abs_v_taper'")
            if "active_split" not in cols:
                cursor.execute("ALTER TABLE users_profile ADD COLUMN active_split TEXT NOT NULL DEFAULT 'Push / Pull / Legs'")

            # 2. workout_plan_logs migration
            cols = get_columns("workout_plan_logs")
            if "session_theme" not in cols:
                cursor.execute("ALTER TABLE workout_plan_logs ADD COLUMN session_theme TEXT DEFAULT 'General'")
            if "rir" not in cols:
                cursor.execute("ALTER TABLE workout_plan_logs ADD COLUMN rir REAL DEFAULT 2.0")

            # 3. nutrition_daily_logs migration
            cols = get_columns("nutrition_daily_logs")
            if "meal_type" not in cols:
                cursor.execute("ALTER TABLE nutrition_daily_logs ADD COLUMN meal_type TEXT DEFAULT 'General'")

            # 4. weight_fatigue_logs migration
            cols = get_columns("weight_fatigue_logs")
            if "notes" not in cols:
                cursor.execute("ALTER TABLE weight_fatigue_logs ADD COLUMN notes TEXT DEFAULT ''")

            conn.commit()

    def upsert_user_profile(self, profile: Dict[str, Any]) -> None:
        sql = """
        INSERT INTO users_profile (
            user_id, name, age, gender, height_cm, weight_kg, activity_level,
            primary_goal, aesthetic_focus, active_split, target_calories, target_protein_g, target_carbs_g,
            target_fat_g, available_equipment, dietary_restrictions, joint_limitations, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            age=excluded.age,
            gender=excluded.gender,
            height_cm=excluded.height_cm,
            weight_kg=excluded.weight_kg,
            activity_level=excluded.activity_level,
            primary_goal=excluded.primary_goal,
            aesthetic_focus=excluded.aesthetic_focus,
            active_split=excluded.active_split,
            target_calories=excluded.target_calories,
            target_protein_g=excluded.target_protein_g,
            target_carbs_g=excluded.target_carbs_g,
            target_fat_g=excluded.target_fat_g,
            available_equipment=excluded.available_equipment,
            dietary_restrictions=excluded.dietary_restrictions,
            joint_limitations=excluded.joint_limitations,
            updated_at=CURRENT_TIMESTAMP;
        """
        params = (
            profile["user_id"], profile["name"], profile["age"], profile["gender"],
            profile["height_cm"], profile["weight_kg"], profile["activity_level"],
            profile["primary_goal"], profile.get("aesthetic_focus", "abs_v_taper"),
            profile.get("active_split", "Push / Pull / Legs"),
            profile["target_calories"], profile["target_protein_g"],
            profile["target_carbs_g"], profile["target_fat_g"],
            json.dumps(profile.get("available_equipment", [])),
            json.dumps(profile.get("dietary_restrictions", [])),
            json.dumps(profile.get("joint_limitations", []))
        )
        with self._get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

    def log_daily_weight_fatigue(self, user_id: str, weight_kg: float, fatigue_score: int = 3, sleep_hours: float = 7.5, notes: str = "") -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO weight_fatigue_logs (user_id, log_date, weight_kg, fatigue_score, sleep_hours, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, log_date) DO UPDATE SET
            weight_kg=excluded.weight_kg,
            fatigue_score=excluded.fatigue_score,
            sleep_hours=excluded.sleep_hours,
            notes=excluded.notes;
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, weight_kg, fatigue_score, sleep_hours, notes))
            conn.commit()

    def log_workout_exercise(self, user_id: str, theme: str, exercise: str, sets: int, reps: int, weight_kg: float, rpe: float = 8.0, rir: float = 2.0, notes: str = "") -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO workout_plan_logs (user_id, log_date, session_theme, exercise_name, sets, reps, weight_kg, rpe, rir, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, theme, exercise, sets, reps, weight_kg, rpe, rir, notes))
            conn.commit()
        self.update_personal_record(user_id, exercise, weight_kg, reps)

    def update_personal_record(self, user_id: str, exercise: str, weight_kg: float, reps: int) -> None:
        if reps <= 0 or weight_kg <= 0:
            return
        est_1rm = round(weight_kg * (1.0 + reps / 30.0), 1)
        today = date.today().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT est_1rm FROM personal_records WHERE user_id = ? AND exercise_name = ?", (user_id, exercise))
            row = cursor.fetchone()
            if not row or est_1rm > row["est_1rm"]:
                conn.execute("""
                INSERT INTO personal_records (user_id, exercise_name, weight_kg, reps, est_1rm, achieved_date)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, exercise_name) DO UPDATE SET
                    weight_kg=excluded.weight_kg,
                    reps=excluded.reps,
                    est_1rm=excluded.est_1rm,
                    achieved_date=excluded.achieved_date;
                """, (user_id, exercise, weight_kg, reps, est_1rm, today))
                conn.commit()

    def get_personal_records(self, user_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM personal_records WHERE user_id = ? ORDER BY est_1rm DESC", (user_id,))
            return [dict(r) for r in cursor.fetchall()]

    def log_nutrition_item(self, user_id: str, description: str, calories: int, protein: float, carbs: float, fat: float, meal_type: str = "General") -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO nutrition_daily_logs (user_id, log_date, meal_type, food_description, actual_calories, actual_protein_g, actual_carbs_g, actual_fat_g)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, meal_type, description, calories, protein, carbs, fat))
            conn.commit()

    def log_recovery_biometrics(self, user_id: str, hrv_ms: float, resting_hr: float, sleep_hours: float, status: str, volume_mult: float, rpe_cap: float) -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO recovery_biometrics (user_id, log_date, hrv_sdnn_ms, resting_hr_bpm, sleep_hours, readiness_status, volume_multiplier, rpe_cap)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, log_date) DO UPDATE SET
            hrv_sdnn_ms=excluded.hrv_sdnn_ms,
            resting_hr_bpm=excluded.resting_hr_bpm,
            sleep_hours=excluded.sleep_hours,
            readiness_status=excluded.readiness_status,
            volume_multiplier=excluded.volume_multiplier,
            rpe_cap=excluded.rpe_cap;
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, hrv_ms, resting_hr, sleep_hours, status, volume_mult, rpe_cap))
            conn.commit()

    def log_physique_photo(self, user_id: str, pose: str, photo_bytes: bytes, ai_feedback: str) -> None:
        today = date.today().isoformat()
        b64_str = base64.b64encode(photo_bytes).decode("utf-8")
        sql = """
        INSERT INTO physique_photos (user_id, log_date, pose, photo_base64, ai_feedback)
        VALUES (?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, pose, b64_str, ai_feedback))
            conn.commit()

    def get_physique_photos(self, user_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT photo_id, log_date, pose, photo_base64, ai_feedback FROM physique_photos WHERE user_id = ? ORDER BY log_date DESC", (user_id,))
            return [dict(r) for r in cursor.fetchall()]

    def log_daily_habits(self, user_id: str, creatine: int, water: int, steps: int, sleep: int, weight: int) -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO daily_habits (user_id, log_date, creatine, water_target, steps_8k, sleep_target, scale_weight)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, log_date) DO UPDATE SET
            creatine=excluded.creatine,
            water_target=excluded.water_target,
            steps_8k=excluded.steps_8k,
            sleep_target=excluded.sleep_target,
            scale_weight=excluded.scale_weight;
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, creatine, water, steps, sleep, weight))
            conn.commit()

    def get_daily_habits(self, user_id: str) -> Dict[str, Any]:
        today = date.today().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_habits WHERE user_id = ? AND log_date = ?", (user_id, today))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {"creatine": 0, "water_target": 0, "steps_8k": 0, "sleep_target": 0, "scale_weight": 0}

    def log_muscle_feedback(self, user_id: str, muscle: str, soreness: int, pump: int) -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO muscle_soreness_pump (user_id, log_date, muscle_group, soreness_rating, pump_rating)
        VALUES (?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, muscle, soreness, pump))
            conn.commit()

    def get_last_performance_for_exercise(self, user_id: str, exercise_name: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT log_date, reps, weight_kg, rpe FROM workout_plan_logs WHERE user_id = ? AND exercise_name = ? ORDER BY log_date DESC, workout_id DESC LIMIT 1",
                (user_id, exercise_name)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_agent_context(self, user_id: str, days_history: int = 14) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Profile
            cursor.execute("SELECT * FROM users_profile WHERE user_id = ?", (user_id,))
            profile_row = cursor.fetchone()
            if not profile_row:
                raise ValueError(f"User {user_id} not found.")

            profile = dict(profile_row)
            profile["available_equipment"] = json.loads(profile["available_equipment"]) if profile["available_equipment"] else []
            profile["dietary_restrictions"] = json.loads(profile["dietary_restrictions"]) if profile["dietary_restrictions"] else []
            profile["joint_limitations"] = json.loads(profile["joint_limitations"]) if profile["joint_limitations"] else []

            # 14-day Check-ins
            cutoff_date = (date.today() - timedelta(days=days_history)).isoformat()
            cursor.execute(
                "SELECT log_date, weight_kg, fatigue_score, sleep_hours FROM weight_fatigue_logs WHERE user_id = ? AND log_date >= ? ORDER BY log_date ASC",
                (user_id, cutoff_date)
            )
            recent_checkins = [dict(row) for row in cursor.fetchall()]

            # 14-day Nutrition History
            cursor.execute(
                "SELECT log_date, SUM(actual_calories) as cal, SUM(actual_protein_g) as p, SUM(actual_carbs_g) as c, SUM(actual_fat_g) as f FROM nutrition_daily_logs WHERE user_id = ? AND log_date >= ? GROUP BY log_date ORDER BY log_date ASC",
                (user_id, cutoff_date)
            )
            recent_nutrition = [dict(row) for row in cursor.fetchall()]

            # Recent Workouts
            cursor.execute(
                "SELECT workout_id, log_date, session_theme, exercise_name, sets, reps, weight_kg, rpe FROM workout_plan_logs WHERE user_id = ? AND log_date >= ? ORDER BY log_date DESC, workout_id DESC",
                (user_id, cutoff_date)
            )
            recent_workouts = [dict(row) for row in cursor.fetchall()]

            # Today's Nutrition
            today = date.today().isoformat()
            cursor.execute(
                "SELECT SUM(actual_calories) as cal, SUM(actual_protein_g) as p, SUM(actual_carbs_g) as c, SUM(actual_fat_g) as f FROM nutrition_daily_logs WHERE user_id = ? AND log_date = ?",
                (user_id, today)
            )
            today_nutr = cursor.fetchone()
            today_nutrition = {
                "calories": (today_nutr["cal"] or 0) if today_nutr else 0,
                "protein_g": round((today_nutr["p"] or 0), 1) if today_nutr else 0.0,
                "carbs_g": round((today_nutr["c"] or 0), 1) if today_nutr else 0.0,
                "fat_g": round((today_nutr["f"] or 0), 1) if today_nutr else 0.0
            }

            # Today's Recovery
            cursor.execute("SELECT * FROM recovery_biometrics WHERE user_id = ? AND log_date = ?", (user_id, today))
            rec_row = cursor.fetchone()
            today_recovery = dict(rec_row) if rec_row else None

            # PRs
            cursor.execute("SELECT * FROM personal_records WHERE user_id = ? ORDER BY est_1rm DESC", (user_id,))
            prs = [dict(r) for r in cursor.fetchall()]

            return {
                "profile": profile,
                "metrics_summary": {
                    "recent_checkins": recent_checkins,
                    "recent_nutrition": recent_nutrition,
                    "recent_workouts": recent_workouts,
                    "today_nutrition": today_nutrition,
                    "today_recovery": today_recovery,
                    "personal_records": prs
                }
            }

    def export_all_data_json(self, user_id: str) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            data = {}
            for table in ["users_profile", "nutrition_daily_logs", "workout_plan_logs", "weight_fatigue_logs", "recovery_biometrics", "daily_habits", "personal_records"]:
                cursor.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,))
                data[table] = [dict(r) for r in cursor.fetchall()]
            return json.dumps(data, indent=2, default=str)
