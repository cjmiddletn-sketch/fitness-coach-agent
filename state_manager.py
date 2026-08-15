import json
import sqlite3
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

class FitnessStateManager:
    def __init__(self, db_path: str = "fitness_agent.db"):
        self.db_path = db_path
        self._init_db()

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
                food_description TEXT,
                actual_calories INTEGER NOT NULL,
                actual_protein_g REAL NOT NULL,
                actual_carbs_g REAL NOT NULL,
                actual_fat_g REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE
            );
            """)

            # 3. Workout Logs Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS workout_plan_logs (
                workout_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                log_date DATE NOT NULL,
                exercise_name TEXT NOT NULL,
                sets INTEGER NOT NULL,
                reps INTEGER NOT NULL,
                weight_kg REAL NOT NULL,
                rpe REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users_profile(user_id) ON DELETE CASCADE
            );
            """)

            # 4. Weight & Fatigue Check-ins Table
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

            # 5. Recovery Biometrics Table (Apple Watch / Wearables)
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
            conn.commit()

    def upsert_user_profile(self, profile: Dict[str, Any]) -> None:
        sql = """
        INSERT INTO users_profile (
            user_id, name, age, gender, height_cm, weight_kg, activity_level,
            primary_goal, target_calories, target_protein_g, target_carbs_g,
            target_fat_g, available_equipment, dietary_restrictions, joint_limitations, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            age=excluded.age,
            height_cm=excluded.height_cm,
            weight_kg=excluded.weight_kg,
            activity_level=excluded.activity_level,
            primary_goal=excluded.primary_goal,
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
            profile["primary_goal"], profile["target_calories"], profile["target_protein_g"],
            profile["target_carbs_g"], profile["target_fat_g"],
            json.dumps(profile.get("available_equipment", [])),
            json.dumps(profile.get("dietary_restrictions", [])),
            json.dumps(profile.get("joint_limitations", []))
        )
        with self._get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

    def log_daily_weight_fatigue(self, user_id: str, weight_kg: float, fatigue_score: int, sleep_hours: float) -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO weight_fatigue_logs (user_id, log_date, weight_kg, fatigue_score, sleep_hours)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, log_date) DO UPDATE SET
            weight_kg=excluded.weight_kg,
            fatigue_score=excluded.fatigue_score,
            sleep_hours=excluded.sleep_hours;
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, weight_kg, fatigue_score, sleep_hours))
            conn.commit()

    def log_workout_exercise(self, user_id: str, exercise: str, sets: int, reps: int, weight_kg: float, rpe: float = None, notes: str = None) -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO workout_plan_logs (user_id, log_date, exercise_name, sets, reps, weight_kg, rpe, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, exercise, sets, reps, weight_kg, rpe, notes))
            conn.commit()

    def log_nutrition_item(self, user_id: str, description: str, calories: int, protein: float, carbs: float, fat: float) -> None:
        today = date.today().isoformat()
        sql = """
        INSERT INTO nutrition_daily_logs (user_id, log_date, food_description, actual_calories, actual_protein_g, actual_carbs_g, actual_fat_g)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            conn.execute(sql, (user_id, today, description, calories, protein, carbs, fat))
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

    def get_agent_context(self, user_id: str, days_history: int = 7) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Profile
            cursor.execute("SELECT * FROM users_profile WHERE user_id = ?", (user_id,))
            profile_row = cursor.fetchone()
            if not profile_row:
                raise ValueError(f"User {user_id} not found.")

            profile = dict(profile_row)
            profile["available_equipment"] = json.loads(profile["available_equipment"])
            profile["dietary_restrictions"] = json.loads(profile["dietary_restrictions"])
            profile["joint_limitations"] = json.loads(profile["joint_limitations"])

            # Recent Check-ins
            cutoff_date = (date.today() - timedelta(days=days_history)).isoformat()
            cursor.execute(
                "SELECT log_date, weight_kg, fatigue_score, sleep_hours FROM weight_fatigue_logs WHERE user_id = ? AND log_date >= ? ORDER BY log_date ASC",
                (user_id, cutoff_date)
            )
            recent_checkins = [dict(row) for row in cursor.fetchall()]

            # Recent Workouts
            cursor.execute(
                "SELECT log_date, exercise_name, sets, reps, weight_kg, rpe, notes FROM workout_plan_logs WHERE user_id = ? AND log_date >= ? ORDER BY log_date DESC",
                (user_id, cutoff_date)
            )
            recent_workouts = [dict(row) for row in cursor.fetchall()]

            # Today's Nutrition Consumed
            today = date.today().isoformat()
            cursor.execute(
                "SELECT SUM(actual_calories) as cal, SUM(actual_protein_g) as p, SUM(actual_carbs_g) as c, SUM(actual_fat_g) as f FROM nutrition_daily_logs WHERE user_id = ? AND log_date = ?",
                (user_id, today)
            )
            today_nutrition = dict(cursor.fetchone() or {})

            # Latest Recovery Biometrics
            cursor.execute(
                "SELECT * FROM recovery_biometrics WHERE user_id = ? AND log_date = ?",
                (user_id, today)
            )
            latest_biometrics = cursor.fetchone()
            recovery_data = dict(latest_biometrics) if latest_biometrics else None

            return {
                "profile": profile,
                "metrics_summary": {
                    "recent_checkins": recent_checkins,
                    "recent_workouts": recent_workouts,
                    "today_nutrition": {
                        "calories": today_nutrition.get("cal") or 0,
                        "protein_g": round(today_nutrition.get("p") or 0, 1),
                        "carbs_g": round(today_nutrition.get("c") or 0, 1),
                        "fat_g": round(today_nutrition.get("f") or 0, 1)
                    },
                    "today_recovery": recovery_data
                }
            }
