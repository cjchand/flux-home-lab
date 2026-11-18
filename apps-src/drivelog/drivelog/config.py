import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    tz: ZoneInfo
    student_name: str
    goal_total_h: float
    goal_night_h: float
    home_lat: float
    home_lon: float

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        return cls(
            db_host=e["DRIVELOG_DB_HOST"],
            db_port=int(e.get("DRIVELOG_DB_PORT", "5432")),
            db_name=e["DRIVELOG_DB_NAME"],
            db_user=e["DRIVELOG_DB_USER"],
            db_password=e["DRIVELOG_DB_PASSWORD"],
            tz=ZoneInfo(e.get("DRIVELOG_TZ", "America/Chicago")),
            student_name=e.get("DRIVELOG_STUDENT_NAME", "Toby"),
            goal_total_h=float(e.get("DRIVELOG_GOAL_TOTAL_H", "30")),
            goal_night_h=float(e.get("DRIVELOG_GOAL_NIGHT_H", "10")),
            home_lat=float(e["DRIVELOG_HOME_LAT"]),
            home_lon=float(e["DRIVELOG_HOME_LON"]),
        )
