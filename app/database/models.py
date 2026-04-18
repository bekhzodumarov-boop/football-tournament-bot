import random
import string
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
    CLOSED = "closed"         # запись закрыта
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    CANCELLED = "cancelled"

class AttendanceResponse(str, PyEnum):
    YES = "yes"
    NO = "no"
    MAYBE = "maybe"
    NO_RESPONSE = "no_response"
    WAITLIST = "waitlist"   # лист ожидания

class MatchStatus(str, PyEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"

class MatchFormat(str, PyEnum):
    TIME = "time"
    GOALS = "goals"

class GoalType(str, PyEnum):
    GOAL = "goal"
    OWN_GOAL = "own_goal"

class CardType(str, PyEnum):
    YELLOW = "yellow"
    RED = "red"


class MatchStage(str, PyEnum):
    GROUP = "group"
    SEMIFINAL = "semifinal"
    THIRD_PLACE = "third_place"
    FINAL = "final"

MATCH_STAGE_LABELS = {
    MatchStage.GROUP:       "📋 Групповой этап",
    MatchStage.SEMIFINAL:   "🏆 Полуфинал",
    MatchStage.THIRD_PLACE: "🥉 Матч за 3 место",
    MatchStage.FINAL:       "🏆 Финал",
}


def _gen_invite_code() -> str:
    """Генерирует случайный 8-символьный инвайт-код (A-Z0-9)."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


# ---------- Models ----------

class League(Base):
    """Лига — изолированная группа игроков со своим расписанием."""
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    invite_code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    card_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    players: Mapped[list["Player"]] = relationship(back_populates="league")
    game_days: Mapped[list["GameDay"]] = relationship(back_populates="league")


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[Position] = mapped_column(Enum(Position, name="player_pos_type"), name="player_position")
    self_rating: Mapped[int] = mapped_column(Integer, default=5)
    rating: Mapped[float] = mapped_column(Float, default=5.0)
    rating_provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    reliability_pct: Mapped[float] = mapped_column(Float, default=100.0)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[PlayerStatus] = mapped_column(Enum(PlayerStatus), default=PlayerStatus.ACTIVE)
    is_referee: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(5), default="ru", nullable=False, server_default="ru")
    gender: Mapped[str] = mapped_column(String(1), default="m", nullable=False, server_default="m")
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    league_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leagues.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    league: Mapped[Optional["League"]] = relationship(back_populates="players")
    attendances: Mapped[list["Attendance"]] = relationship(back_populates="player")
    goals: Mapped[list["Goal"]] = relationship(back_populates="player")
    payments: Mapped[list["Payment"]] = relationship(back_populates="player")


class GameDay(Base):
    __tablename__ = "game_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    league_id: Mapped[Optional[int]] = mapped_column(ForeignKey("leagues.id"), nullable=True)
    tournament_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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
    league: Mapped[Optional["League"]] = relationship(back_populates="game_days")
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
        now = datetime.now()
        if self.status != GameDayStatus.ANNOUNCED:
            return False
        if self.registration_deadline and now > self.registration_deadline:
            return False
        return True  # Запись открыта; waitlist включается автоматически при достижении лимита

    @property
    def display_name(self) -> str:
        if self.tournament_number:
            return f"Турнир #{self.tournament_number}"
        return self.scheduled_at.strftime("%d.%m.%Y")


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

    game_day: Mapped["GameDay"] = relationship(back_populates="attendances")
    player: Mapped["Player"] = relationship(back_populates="attendances")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_day_id: Mapped[int] = mapped_column(ForeignKey("game_days.id"))
    name: Mapped[str] = mapped_column(String(50))
    color_emoji: Mapped[str] = mapped_column(String(10), default="⚪")
    captain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"), nullable=True)

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
    duration_min: Mapped[int] = mapped_column(Integer, default=20)
    goals_to_win: Mapped[int] = mapped_column(Integer, default=3)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    match_stage: Mapped[Optional[str]] = mapped_column(String(20), default="group", nullable=True)
    match_order: Mapped[int] = mapped_column(Integer, default=0)  # порядок в расписании (0 = вне расписания)

    game_day: Mapped["GameDay"] = relationship(back_populates="matches")
    team_home: Mapped["Team"] = relationship(foreign_keys=[team_home_id])
    team_away: Mapped["Team"] = relationship(foreign_keys=[team_away_id])
    goals: Mapped[list["Goal"]] = relationship(back_populates="match")
    cards: Mapped[list["Card"]] = relationship(back_populates="match")


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
    triggered_by: Mapped[str] = mapped_column(String(50))
    game_day_id: Mapped[Optional[int]] = mapped_column(ForeignKey("game_days.id"), nullable=True)
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
    score: Mapped[int] = mapped_column(Integer)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    round: Mapped["RatingRound"] = relationship(back_populates="votes")
    voter: Mapped["Player"] = relationship(foreign_keys=[voter_id])
    nominee: Mapped["Player"] = relationship(foreign_keys=[nominee_id])


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    card_type: Mapped[CardType] = mapped_column(Enum(CardType))
    issued_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    match: Mapped["Match"] = relationship(back_populates="cards")
    player: Mapped["Player"] = relationship()
    team: Mapped["Team"] = relationship()
