import sqlite3
import datetime
from typing import List, Dict, Optional, Tuple

class Database:
    def __init__(self, db_file: str = "workbot.db"):
        self.db_file = db_file
        self.init_database()

    def init_database(self):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # 출근/퇴근 기록 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS work_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    date DATE,
                    week_number INTEGER,
                    weekly_hours REAL,
                    status TEXT CHECK(status IN ('WORKING', 'ON_BREAK', 'ENDED'))
                )
            ''')

            # 휴식 기록 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS break_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_record_id INTEGER,  -- 연관된 work_record의 ID
                    user_id TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    FOREIGN KEY (work_record_id) REFERENCES work_records(id)
                )
            ''')

            # 관리자 역할 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_roles (
                    role_id INTEGER PRIMARY KEY
                )
            ''')

            # 회의 테이블
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    meeting_time TIMESTAMP,
                    created_by TEXT,
                    channel_id TEXT,
                    voice_channel_id TEXT,
                    role_id TEXT
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS meeting_members (
                    meeting_id INTEGER,
                    member_id TEXT,
                    FOREIGN KEY (meeting_id) REFERENCES meetings(id),
                    PRIMARY KEY (meeting_id, member_id)
                )
            ''')
            
            conn.commit()

    def get_active_work_record(self, user_id: str) -> Optional[Tuple]:
        """현재 진행 중인 work_record를 가져옴"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, start_time, end_time
                FROM work_records 
                WHERE user_id = ? AND end_time IS NULL
                ORDER BY start_time DESC 
                LIMIT 1
            """, (user_id,))
            return cursor.fetchone()

    def get_active_break(self, user_id: str) -> Optional[Tuple]:
        """현재 진행 중인 break_record를 가져옴"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, work_record_id, start_time, end_time
                FROM break_records 
                WHERE user_id = ? AND end_time IS NULL
                ORDER BY start_time DESC 
                LIMIT 1
            """, (user_id,))
            return cursor.fetchone()

    def clock_in(self, user_id: str) -> bool:
        try:
            if self.is_clocked_in(user_id):
                return False
                
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                now = datetime.datetime.now()
                date = now.date()
                week_number = self._get_week_number(date)
                
                cursor.execute("""
                    INSERT INTO work_records 
                    (user_id, start_time, date, week_number, weekly_hours, status)
                    VALUES (?, ?, ?, ?, ?, 'WORKING')
                """, (user_id, now, date, week_number, 0))
                return True
        except sqlite3.Error:
            return False

    def clock_out(self, user_id: str) -> bool:
        # 진행 중인 휴식이 있는지 확인
        active_break = self.get_active_break(user_id)
        if active_break:
            return False

        active_work = self.get_active_work_record(user_id)
        if not active_work:
            return False

        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now()
            
            # 퇴근 처리
            cursor.execute("""
                UPDATE work_records 
                SET end_time = ?
                WHERE id = ?
            """, (now, active_work[0]))

            # 주간 근무 시간 업데이트
            week_number = self._get_week_number(now.date())
            weekly_hours = self._calculate_weekly_hours(user_id, week_number)
            cursor.execute("""
                UPDATE work_records
                SET weekly_hours = ?
                WHERE user_id = ? AND week_number = ?
            """, (weekly_hours, user_id, week_number))
            
            return True

    def start_break(self, user_id: str) -> bool:
        if not self.is_clocked_in(user_id) or self.is_on_break(user_id):
            return False
            
        work_record = self.get_active_work_record(user_id)
        if not work_record:
            return False
            
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now()
            
            # 현재 근무 상태를 WORKING에서 ON BREAK로 변경하기
            cursor.execute("""
                UPDATE work_records
                SET status = 'ON_BREAK'
                WHERE id = ? AND status = 'WORKING'
            """, (work_record[0],))
            
            # 휴식 레코드 만들기
            cursor.execute("""
                INSERT INTO break_records 
                (work_record_id, user_id, start_time)
                VALUES (?, ?, ?)
            """, (work_record[0], user_id, now))
            
            return True

    def end_break(self, user_id: str) -> bool:
        if not self.is_on_break(user_id):
            return False
            
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            now = datetime.datetime.now()
            
            # 현재 근무 상태 확인
            work_record = self.get_active_work_record(user_id)
            if not work_record:
                return False
                
            # 근무 상태를 ON BREAK에서 WORKING으로 변경
            cursor.execute("""
                UPDATE work_records
                SET status = 'WORKING'
                WHERE id = ? AND status = 'ON_BREAK'
            """, (work_record[0],))
            
            # 휴식 레코드 업데이트
            cursor.execute("""
                UPDATE break_records 
                SET end_time = ?
                WHERE user_id = ? AND end_time IS NULL
            """, (now, user_id))
            
            return True

    def _calculate_work_hours_excluding_breaks(
        self, 
        work_start: datetime.datetime, 
        work_end: datetime.datetime, 
        user_id: str,
        work_record_id: int
    ) -> float:
        """휴식 시간을 제외한 실제 근무 시간 계산"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT start_time, end_time
                FROM break_records
                WHERE work_record_id = ? AND user_id = ?
                AND start_time >= ? AND end_time <= ?
            """, (work_record_id, user_id, work_start, work_end))
            
            breaks = cursor.fetchall()
            total_break_hours = sum(
                (datetime.datetime.fromisoformat(end) - 
                 datetime.datetime.fromisoformat(start)).total_seconds() / 3600
                for start, end in breaks if end is not None
            )
            
            total_work_hours = (work_end - work_start).total_seconds() / 3600
            return max(0, total_work_hours - total_break_hours)

    def _calculate_weekly_hours(self, user_id: str, week_number: int) -> float:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, start_time, end_time
                FROM work_records
                WHERE user_id = ? AND week_number = ? AND end_time IS NOT NULL
            """, (user_id, week_number))
            
            total_hours = 0
            for work_id, start, end in cursor.fetchall():
                start_dt = datetime.datetime.fromisoformat(start)
                end_dt = datetime.datetime.fromisoformat(end)
                work_hours = self._calculate_work_hours_excluding_breaks(
                    start_dt, end_dt, user_id, work_id
                )
                total_hours += work_hours
                
            return round(total_hours, 2)

    def get_work_summary(self, user_id: str) -> Dict:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            today = datetime.datetime.now().date()
            week_number = self._get_week_number(today)
            
            # Get today's completed work records
            cursor.execute("""
                SELECT id, start_time, end_time
                FROM work_records
                WHERE user_id = ? AND date = ? AND end_time IS NOT NULL
            """, (user_id, today))
            
            daily_hours = 0
            for work_id, start, end in cursor.fetchall():
                start_dt = datetime.datetime.fromisoformat(start)
                end_dt = datetime.datetime.fromisoformat(end)
                work_hours = self._calculate_work_hours_excluding_breaks(
                    start_dt, end_dt, user_id, work_id
                )
                daily_hours += work_hours
            
            # Get current active work record if exists
            active_work = self.get_active_work_record(user_id)
            if active_work:
                start_dt = datetime.datetime.fromisoformat(active_work[1])
                current_dt = datetime.datetime.now()
                active_hours = self._calculate_work_hours_excluding_breaks(
                    start_dt, current_dt, user_id, active_work[0]
                )
                daily_hours += active_hours
            
            weekly_hours = self._calculate_weekly_hours(user_id, week_number)
            
            return {
                "daily_hours": round(daily_hours, 2),
                "weekly_hours": weekly_hours
            }
    def get_current_working_users(self) -> List[str]:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id
                FROM work_records
                WHERE end_time IS NULL
            """)
            return [row[0] for row in cursor.fetchall()]

    def _get_week_number(self, date: datetime.date) -> int:
        return date.isocalendar()[1]

    def is_clocked_in(self, user_id: str) -> bool:
        return self.get_active_work_record(user_id) is not None

    def is_on_break(self, user_id: str) -> bool:
        return self.get_active_break(user_id) is not None

    def add_admin_role(self, role_id: int) -> bool:
        try:
            with sqlite3.connect(self.db_file) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO admin_roles (role_id) VALUES (?)", (role_id,))
                return True
        except sqlite3.IntegrityError:
            return False

    def get_admin_roles(self) -> List[int]:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT role_id FROM admin_roles")
            return [row[0] for row in cursor.fetchall()]

    def create_meeting(
        self, 
        title: str,
        meeting_time: str,
        created_by: str,
        channel_id: str,
        voice_channel_id: str,
        role_id: str,
        member_ids: List[str]
    ) -> int:
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO meetings 
                (title, meeting_time, created_by, channel_id, voice_channel_id, role_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, meeting_time, created_by, channel_id, voice_channel_id, role_id)
            )
            meeting_id = cursor.lastrowid
            
            # Add meeting members
            cursor.executemany(
                "INSERT INTO meeting_members (meeting_id, member_id) VALUES (?, ?)",
                [(meeting_id, member_id) for member_id in member_ids]
            )
            return meeting_id
