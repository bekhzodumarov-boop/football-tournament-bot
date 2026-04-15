from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Enum, Text, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---------- Enums ----------

class Position(str, PyEnum):
    GK = "GK"       # Вратарь
    DEF = "DEF"     # Защитник
    MID = "MID"     # Полузащитник
    FWD = "FWD"     # Нападающий

POSITION_LABELS = {
    Position.GK:  "🧤 Вратарь",
    Position.DEF: "🛡 Защитник",
    Position.MID: "⚙️ Полузащитник",
    Position.FWD: "⚡️ Нападающий",
}

class PlayerStatus(str, PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"

class GameDayStatus(str, PyEnum):
    ANNOUNCED = "announced"   # создан, идёт запись
    CLOSED = "closed"         # запись закрыта, команды ещё не сформированы
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"

class AttendanceResponse(str, PyEnum):
    YES = "yes"
    NO = "no"
    MAYBE = "maybe"
    NO_RESPONSE = "no_response"

class MatchStatus(str, PyEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"

class MatchFormat(str, PyEnum):
    TIME = "time"      # по времени
    GOALS = "goals"    # до N голов

class GoalType(str, PyEnum):
    GOAL = "goal"
    OWN_GOAL = "own_goal"


# ---------- Models ----------

class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[Position] = mapped_column(Enum(Position), name="player_position")
    self_rating: Mapped[int] = mapped_column(Integer, default=5)  # самооценка 1-10
    rating: Mapped[float] = mapped_column(Float, default=5.0)     # итоговый рейтинг
    rating_provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    reliability_pct: Mapped[float] = mapped_column(Float, default=100.0)
    balance: Mapped[int] = mapped_column(Integer, default=0)      # в рублях
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PlayerStatus] = mapped_column(Enum(PlayerStatus), default=PlayerStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    attendances: Mapped[list["Attendance"]] = relationship(back_populates="player")
    goals: Mapped[list["Goal"]] = relationship(back_populates="player")
    payments: Mapped[list["Payment"]] = relationship(back_populates="player")


class GameDay(Base):
    __tablename__ = "game_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[str] = mapped_column(String(200))
    player_limit: Mapped[int] = mapped_column(Integer, default=20)
    registration_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cost_per_player: Mapped[int] = mapped_column(Integer, default=0)
    match_format: Mapped[MatchFormat] = mapped_column(Enum(MatchFormat), default=MatchFormat.TIME)
    match_duration_min: Mapped[int] = mapped_column(Integer, default=30)
    goals_to_win: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[GameDayStatus] = mapped_column(Enum(GameDayStatus), default=GameDayStatus.ANNOUNCED)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    attendances: Mapped[list["Attendance"]] = relationship(back_populates="game_day")
    teams: Mapped[list["Team"]] = relationship(back_populates="game_day")
    matches: Mapped[list["Match"]] = relationship(back_populates="game_day")
    payments: Mapped[list["Payment"]] = relationship(back_populates="game_day")

    @property
    def registered_count(self) -> int:
        return sum(1 for a in self.attendances if a.response == AttendanceResponse.YES)

    @property
    def spots_left(self) -> int:
        return max(0, self.player_limit - self.registered_count)

    @property
    def is_open(self) -> bool:
        from datetime import timezone
        now = datetime.now()
        if self.status != GameDayStatus.ANNOUNCED:
            return False
        if self.registration_deadline and now > self.registration_deadline:
            return False
        return self.spots_left > 0


class Attendance(Base):
    __tablename__ = "attendances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_day_id: Mapped[int] = mapped_column(ForeignKey("game_days.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    response: Mapped[AttendanceResponse] = mapped_column(
        Enum(AttendanceResponse), default=AttendanceResponse.NO_RESPONSE
    )
    confirmed_final: Mapped[bool] = mapped_column(Boolean, default=False)
    actually_came: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    game_day: Mapped["GameDay"] = relationship(back_populates="attendances")
    player: Mapped["Player"] = relationship(back_populates="attendances")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_day_id: Mapped[int] = mapped_column(ForeignKey("game_days.id"))
    name: Mapped[str] = mapped_column(String(50))
    color_emoji: Mapped[str] = mapped_column(String(10), default="⚪")
    captain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"), nullable=True)

    # Relationships
    game_day: Mapped["GameDay"] = relationship(back_populates="teams")
    captain: Mapped[Optional["Player"]] = relationship(foreign_keys=[captain_id])
    players: Mapped[list["TeamPlayer"]] = relationship(back_populates="team")


class TeamPlayer(Base):
    __tablename__ = "team_players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))

    team: Mapped["Team"] = relationship(back_populates="players")
    player: Mapped["Player"] = relationship()


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_day_id: Mapped[int] = mapped_column(ForeignKey("game_days.id"))
    team_home_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    team_away_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    score_home: Mapped[int] = mapped_column(Integer, default=0)
    score_away: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), default=MatchStatus.SCHEDULED)
    match_format: Mapped[MatchFormat] = mapped_column(Enum(MatchFormat), default=MatchFormat.TIME)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    game_day: Mapped["GameDay"] = relationship(back_populates="matches")
    team_home: Mapped["Team"] = relationship(foreign_keys=[team_home_id])
    team_away: Mapped["Team"] = relationship(foreign_keys=[team_away_id])
    goals: Mapped[list["Goal"]] = relationship(back_populates="match")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    goal_type: Mapped[GoalType] = mapped_column(Enum(GoalType), default=GoalType.GOAL)
    scored_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    match: Mapped["Match"] = relationship(back_populates="goals")
    player: Mapped["Player"] = relationship(back_populates="goals")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_day_id: Mapped[int] = mapped_column(ForeignKey("game_days.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    amount: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    game_day: Mapped["GameDay"] = relationship(back_populates="payments")
    player: Mapped["Player"] = relationship(back_populates="payments")


class RatingRound(Base):
    __tablename__ = "rating_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    triggered_by: Mapped[str] = mapped_column(String(50))  # admin / auto / new_player
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")

    votes: Mapped[list["RatingVote"]] = relationship(back_populates="round")


class RatingVote(Base):
    __tablename__ = "rating_votes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rating_rounds.id"))
    voter_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    nominee_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    score: Mapped[int] = mapped_column(Integer)        # 1-10
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    round: Mapped["RatingRound"] = relationship(back_populates="votes")
    voter: Mapped["Player"] = relationship(foreign_keys=[voter_id])
    nominee: Mapped["Player"] = relationship(foreign_keys=[nominee_id])
