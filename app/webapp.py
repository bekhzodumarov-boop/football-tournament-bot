"""
Telegram WebApp — живая таблица турнира + судейская панель.
aiohttp-сервер слушает на PORT (Railway).
  GET /          → HTML-страница с таблицей
  GET /api/standings  → JSON с данными турнира
  GET /referee   → Судейская WebApp
  GET /api/referee/gameday/{game_day_id}   → матчи дня
  GET /api/referee/match/{match_id}        → детали матча
  POST /api/referee/match/{match_id}/start      → старт матча
  POST /api/referee/match/{match_id}/finish     → финиш матча
  POST /api/referee/match/{match_id}/goal       → зафиксировать гол
  POST /api/referee/match/{match_id}/card       → зафиксировать карточку
  POST /api/referee/match/{match_id}/sub        → замена игрока
  POST /api/referee/match/{match_id}/goalkeeper → назначить вратаря
  POST /api/referee/match/{match_id}/save       → отметить сейв
  POST /api/referee/gameday/{game_day_id}/finish → завершить игровой день
  DELETE /api/referee/goal/{goal_id}             → удалить гол
"""
import json
import os
from datetime import datetime, timezone
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.engine import AsyncSessionFactory
from app.database.models import (
    GameDay, GameDayStatus, Match, MatchStatus, MatchFormat, Team, TeamPlayer,
    Goal, GoalType, Card, CardType, Attendance, AttendanceResponse, Player,
    MatchGoalkeeper, PenaltyShootout,
)

# ─── HTML ────────────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🏆 Таблица турнира</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {
    --bg:      var(--tg-theme-bg-color, #1c1c1e);
    --bg2:     var(--tg-theme-secondary-bg-color, #2c2c2e);
    --text:    var(--tg-theme-text-color, #ffffff);
    --hint:    var(--tg-theme-hint-color, #8e8e93);
    --accent:  var(--tg-theme-button-color, #30d158);
    --border:  rgba(255,255,255,0.08);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 14px;
    padding: 12px;
    min-height: 100vh;
  }
  h2 { font-size: 17px; font-weight: 700; margin-bottom: 4px; }
  .subtitle { color: var(--hint); font-size: 12px; margin-bottom: 16px; }
  .section { margin-bottom: 20px; }
  .section-title {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    color: var(--hint); letter-spacing: 0.5px; margin-bottom: 8px;
  }
  /* Standings table */
  .standings {
    background: var(--bg2); border-radius: 12px; overflow: hidden;
  }
  .row {
    display: grid;
    grid-template-columns: 24px 1fr 28px 28px 28px 28px 42px 32px;
    align-items: center;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    gap: 4px;
  }
  .row:last-child { border-bottom: none; }
  .row.header {
    font-size: 11px; font-weight: 600; color: var(--hint);
    padding: 8px 12px;
    background: rgba(255,255,255,0.03);
  }
  .pos { color: var(--hint); font-size: 13px; text-align: center; }
  .pos.top { color: var(--accent); font-weight: 700; }
  .team-name { font-weight: 600; font-size: 14px; overflow: hidden;
    white-space: nowrap; text-overflow: ellipsis; }
  .num { text-align: center; color: var(--hint); font-size: 13px; }
  .pts { text-align: center; font-weight: 700; font-size: 14px; color: var(--accent); }
  .gd { text-align: center; font-size: 12px; color: var(--hint); }
  /* Results */
  .match-card {
    background: var(--bg2); border-radius: 10px;
    padding: 10px 14px; margin-bottom: 8px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .match-teams { display: flex; align-items: center; gap: 8px; flex: 1; }
  .match-team { flex: 1; }
  .match-team.home { text-align: right; }
  .match-team.away { text-align: left; }
  .score {
    font-size: 18px; font-weight: 800; color: var(--accent);
    min-width: 48px; text-align: center;
  }
  .upcoming .score { color: var(--hint); font-size: 14px; }
  .empty { color: var(--hint); font-size: 13px; padding: 12px; text-align: center; }
  /* Refresh bar */
  .refresh-bar {
    display: flex; align-items: center; justify-content: center;
    gap: 6px; color: var(--hint); font-size: 11px; margin-top: 16px;
  }
  .dot {
    width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
    animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
</style>
</head>
<body>
<div id="app"><div class="empty">Загрузка…</div></div>

<script>
Telegram.WebApp.ready();
Telegram.WebApp.expand();

let countdown = 30;

async function load() {
  try {
    const r = await fetch('/api/standings');
    const d = await r.json();
    render(d);
    countdown = 30;
  } catch(e) {
    document.getElementById('app').innerHTML =
      '<div class="empty">⚠️ Ошибка загрузки. Обновите страницу.</div>';
  }
}

function render(d) {
  const app = document.getElementById('app');
  let html = '';

  // Header
  html += `<h2>🏆 Таблица турнира</h2>
  <div class="subtitle">${d.date || ''} · ${d.location || ''}</div>`;

  // Standings
  html += '<div class="section"><div class="section-title">Таблица</div>';
  if (d.standings.length === 0) {
    html += '<div class="standings"><div class="empty">Матчей ещё не сыграно</div></div>';
  } else {
    html += '<div class="standings">';
    html += `<div class="row header">
      <span></span><span>Команда</span>
      <span class="num">И</span><span class="num">В</span>
      <span class="num">Н</span><span class="num">П</span>
      <span class="gd">ГЗ:ГП</span><span class="pts">О</span>
    </div>`;
    d.standings.forEach((s, i) => {
      const posClass = i < 2 ? 'pos top' : 'pos';
      html += `<div class="row">
        <span class="${posClass}">${i+1}</span>
        <span class="team-name">${s.emoji} ${s.name}</span>
        <span class="num">${s.gp}</span>
        <span class="num">${s.w}</span>
        <span class="num">${s.d}</span>
        <span class="num">${s.l}</span>
        <span class="gd">${s.gf}:${s.ga}</span>
        <span class="pts">${s.pts}</span>
      </div>`;
    });
    html += '</div>';
  }
  html += '</div>';

  // Recent results
  html += '<div class="section"><div class="section-title">Последние результаты</div>';
  if (d.results.length === 0) {
    html += '<div class="empty">Матчей ещё нет</div>';
  } else {
    d.results.forEach(m => {
      html += `<div class="match-card">
        <div class="match-teams">
          <div class="match-team home">${m.home}</div>
          <div class="score">${m.score_home}:${m.score_away}</div>
          <div class="match-team away">${m.away}</div>
        </div>
      </div>`;
    });
  }
  html += '</div>';

  // Upcoming
  if (d.upcoming.length > 0) {
    html += '<div class="section upcoming"><div class="section-title">Предстоящие матчи</div>';
    d.upcoming.forEach(m => {
      html += `<div class="match-card">
        <div class="match-teams">
          <div class="match-team home">${m.home}</div>
          <div class="score">vs</div>
          <div class="match-team away">${m.away}</div>
        </div>
      </div>`;
    });
    html += '</div>';
  }

  // Refresh indicator
  html += `<div class="refresh-bar"><div class="dot"></div>
    <span id="countdown">Обновление через ${countdown} сек.</span></div>`;
  app.innerHTML = html;
}

// Countdown ticker
setInterval(() => {
  countdown = Math.max(0, countdown - 1);
  const el = document.getElementById('countdown');
  if (el) el.textContent = `Обновление через ${countdown} сек.`;
}, 1000);

// Auto-refresh every 30 seconds
setInterval(load, 30000);
load();
</script>
</body>
</html>"""


# ─── API ─────────────────────────────────────────────────────────────────────

async def api_standings(request: web.Request) -> web.Response:
    """JSON API: текущая турнирная таблица для последнего активного дня."""
    async with AsyncSessionFactory() as session:
        # Последний активный или завершённый игровой день
        result = await session.execute(
            select(GameDay)
            .where(GameDay.status.in_([
                GameDayStatus.ANNOUNCED, GameDayStatus.CLOSED,
                GameDayStatus.IN_PROGRESS, GameDayStatus.FINISHED,
            ]))
            .order_by(GameDay.scheduled_at.desc())
            .limit(1)
        )
        game_day = result.scalar_one_or_none()

        if not game_day:
            return web.json_response({
                "date": "", "location": "",
                "standings": [], "results": [], "upcoming": [],
            })

        # Матчи
        matches_result = await session.execute(
            select(Match)
            .options(selectinload(Match.team_home), selectinload(Match.team_away))
            .where(Match.game_day_id == game_day.id)
            .order_by(Match.id)
        )
        matches = matches_result.scalars().all()

        # Таблица
        stats: dict[int, dict] = {}
        for m in matches:
            if m.status != MatchStatus.FINISHED:
                continue
            for team, gf, ga in [
                (m.team_home, m.score_home, m.score_away),
                (m.team_away, m.score_away, m.score_home),
            ]:
                if team.id not in stats:
                    stats[team.id] = {
                        "name": team.name, "emoji": team.color_emoji,
                        "gp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0,
                    }
                s = stats[team.id]
                s["gp"] += 1; s["gf"] += gf; s["ga"] += ga
                if gf > ga: s["w"] += 1
                elif gf == ga: s["d"] += 1
                else: s["l"] += 1

        for s in stats.values():
            s["pts"] = s["w"] * 3 + s["d"]

        standings = sorted(stats.values(),
                           key=lambda x: (-x["pts"], -(x["gf"] - x["ga"]), -x["gf"]))

        # Результаты (последние 10)
        finished = [m for m in matches if m.status == MatchStatus.FINISHED]
        results = [
            {"home": m.team_home.name, "away": m.team_away.name,
             "score_home": m.score_home, "score_away": m.score_away}
            for m in finished[-10:]
        ]

        # Предстоящие
        upcoming = [
            {"home": m.team_home.name, "away": m.team_away.name}
            for m in matches if m.status == MatchStatus.SCHEDULED
        ][:5]

        return web.json_response({
            "date": game_day.scheduled_at.strftime("%d.%m.%Y"),
            "location": game_day.location,
            "standings": standings,
            "results": results,
            "upcoming": upcoming,
        })


async def index(request: web.Request) -> web.Response:
    return web.Response(text=_HTML, content_type="text/html")


# ─── REFEREE HTML ─────────────────────────────────────────────────────────────

_REFEREE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>⚽ Судья</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root {
    --bg:      var(--tg-theme-bg-color, #1c1c1e);
    --bg2:     var(--tg-theme-secondary-bg-color, #2c2c2e);
    --text:    var(--tg-theme-text-color, #ffffff);
    --hint:    var(--tg-theme-hint-color, #8e8e93);
    --accent:  var(--tg-theme-button-color, #30d158);
    --accent-t: var(--tg-theme-button-text-color, #ffffff);
    --danger:  #ff453a;
    --yellow:  #ffd60a;
    --red:     #ff453a;
    --border:  rgba(255,255,255,0.08);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    font-size: 15px;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* ── Views ── */
  .view { display: none; flex-direction: column; min-height: 100vh; opacity: 0; transition: opacity 0.18s ease; }
  .view.active { display: flex; opacity: 1; }

  /* ── Header ── */
  .header {
    background: var(--bg2);
    padding: 12px 16px;
    display: flex; align-items: center; gap: 10px;
    border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 10;
  }
  .header-back {
    background: none; border: none; color: var(--accent);
    font-size: 17px; cursor: pointer; padding: 6px 0; min-width: 44px;
    text-align: left;
  }
  .header-title { font-weight: 700; font-size: 17px; flex: 1; }
  .header-sub { font-size: 12px; color: var(--hint); }

  /* ── Content ── */
  .content { flex: 1; padding: 12px 16px; }

  /* ── Section ── */
  .section { margin-bottom: 20px; }
  .section-title {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    color: var(--hint); letter-spacing: 0.5px; margin-bottom: 8px; padding: 0 2px;
  }

  /* ── Match List ── */
  .match-list-card {
    background: var(--bg2); border-radius: 12px;
    padding: 14px 16px; margin-bottom: 8px;
    display: flex; align-items: center; gap: 12px;
    cursor: pointer; transition: opacity 0.1s;
    border: 1px solid var(--border);
    min-height: 64px;
  }
  .match-list-card:active { opacity: 0.7; }
  .match-list-status { font-size: 20px; flex-shrink: 0; }
  .match-list-body { flex: 1; min-width: 0; }
  .match-list-teams { font-weight: 600; font-size: 14px; }
  .match-list-score {
    font-size: 18px; font-weight: 800; color: var(--accent);
    flex-shrink: 0; min-width: 48px; text-align: center;
  }
  .match-list-score.scheduled { color: var(--hint); font-size: 14px; }
  .match-list-meta { font-size: 12px; color: var(--hint); margin-top: 2px; }

  /* ── Match Panel ── */
  .score-board {
    background: var(--bg2); border-radius: 16px;
    padding: 20px 16px; margin-bottom: 16px;
    text-align: center;
  }
  .score-teams {
    display: grid; grid-template-columns: 1fr auto 1fr;
    gap: 8px; align-items: center; margin-bottom: 12px;
  }
  .score-team-name { font-weight: 700; font-size: 15px; }
  .score-team-name.home { text-align: right; }
  .score-team-name.away { text-align: left; }
  .score-digits {
    font-size: 48px; font-weight: 900; color: var(--accent);
    line-height: 1; letter-spacing: -2px;
  }
  .timer-row {
    font-size: 13px; color: var(--hint); margin-top: 6px;
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .timer-live {
    color: var(--accent); font-weight: 700;
    font-size: 38px; line-height: 1;
    letter-spacing: -1px; font-variant-numeric: tabular-nums;
  }

  /* ── Score controls ── */
  .score-controls {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 8px; margin-bottom: 12px;
  }
  .score-side { display: flex; gap: 6px; }
  .score-side.home { flex-direction: row-reverse; }
  .score-side.away { flex-direction: row; }
  .score-btn {
    min-height: 52px; flex: 1;
    border: none; border-radius: 12px; cursor: pointer;
    font-size: 22px; font-weight: 700; transition: opacity 0.1s;
  }
  .score-btn:active { opacity: 0.7; }
  .score-btn.plus { background: var(--accent); color: var(--accent-t); }
  .score-btn.minus { background: var(--bg2); color: var(--hint); border: 1px solid var(--border); }

  /* ── Action buttons ── */
  .action-row { display: flex; gap: 8px; margin-bottom: 8px; }
  .btn {
    flex: 1; min-height: 48px; border: none; border-radius: 12px;
    font-size: 15px; font-weight: 600; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    gap: 6px; transition: opacity 0.1s;
  }
  .btn:active { opacity: 0.7; }
  .btn-primary { background: var(--accent); color: var(--accent-t); }
  .btn-danger { background: var(--danger); color: #fff; }
  .btn-neutral { background: var(--bg2); color: var(--text); border: 1px solid var(--border); }
  .btn-yellow { background: var(--yellow); color: #000; }
  .btn-red { background: var(--red); color: #fff; }
  .btn-disabled { background: var(--bg2); color: var(--hint); border: 1px solid var(--border); cursor: default; }

  /* ── Events list ── */
  .events-list { background: var(--bg2); border-radius: 12px; overflow: hidden; }
  .event-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-bottom: 1px solid var(--border);
  }
  .event-item:last-child { border-bottom: none; }
  .event-icon { font-size: 18px; flex-shrink: 0; }
  .event-body { flex: 1; min-width: 0; }
  .event-player { font-weight: 600; font-size: 14px; }
  .event-meta { font-size: 12px; color: var(--hint); }
  .event-del {
    background: none; border: none; color: var(--danger);
    font-size: 18px; cursor: pointer; padding: 4px 8px; min-width: 44px; text-align: center;
  }

  /* ── Player Grid ── */
  .player-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
    margin-bottom: 12px;
  }
  .player-btn {
    min-height: 52px; background: var(--bg2); border: 1px solid var(--border);
    border-radius: 12px; color: var(--text); font-size: 14px; font-weight: 600;
    cursor: pointer; transition: opacity 0.1s; padding: 10px;
  }
  .player-btn:active { opacity: 0.7; }
  .own-goal-btn {
    width: 100%; min-height: 52px; background: rgba(255,69,58,0.15);
    border: 1px solid var(--danger); border-radius: 12px;
    color: var(--danger); font-size: 15px; font-weight: 600;
    cursor: pointer; margin-bottom: 8px;
  }

  /* ── Loading ── */
  .spinner {
    display: inline-block; width: 20px; height: 20px;
    border: 3px solid var(--border); border-top-color: var(--accent);
    border-radius: 50%; animation: spin 0.7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: none; align-items: center; justify-content: center; z-index: 100;
  }
  .loading-overlay.show { display: flex; }

  .empty { color: var(--hint); text-align: center; padding: 24px; font-size: 14px; }

  /* Duration picker modal */
  .dur-overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.55);
    display: none; align-items: flex-end; justify-content: center; z-index: 200;
  }
  .dur-overlay.show { display: flex; }
  .dur-sheet {
    background: var(--bg2); border-radius: 20px 20px 0 0;
    padding: 20px 16px 32px; width: 100%; max-width: 480px;
  }
  .dur-title { font-size: 17px; font-weight: 700; margin-bottom: 16px; text-align: center; }
  .dur-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; margin-bottom: 14px; }
  .dur-btn {
    min-height: 52px; background: var(--bg); border: 1px solid var(--border);
    border-radius: 12px; color: var(--text); font-size: 16px; font-weight: 600;
    cursor: pointer; transition: opacity .1s;
  }
  .dur-btn:active { opacity: .7; }
  .dur-btn.selected { background: var(--accent); color: var(--accent-t); border-color: var(--accent); }
  .dur-custom {
    display: flex; gap: 8px; align-items: center; margin-bottom: 14px;
  }
  .dur-custom input {
    flex: 1; padding: 12px; border-radius: 12px; border: 1px solid var(--border);
    background: var(--bg); color: var(--text); font-size: 16px; text-align: center;
  }

  /* ── Penalty Shootout ── */
  .penalty-panel {
    background: var(--bg2); border-radius: 14px;
    padding: 16px; margin-bottom: 16px;
    border: 1px solid rgba(255,69,58,0.3);
  }
  .penalty-title {
    text-align: center; font-size: 13px; font-weight: 700;
    color: var(--danger); text-transform: uppercase; letter-spacing: 0.5px;
    margin-bottom: 10px;
  }
  .penalty-score {
    display: grid; grid-template-columns: 1fr auto 1fr;
    align-items: center; gap: 8px; margin-bottom: 12px;
  }
  .penalty-team { font-weight: 700; font-size: 13px; text-align: center; }
  .penalty-digits {
    font-size: 36px; font-weight: 900; color: var(--danger);
    line-height: 1; letter-spacing: -1px; text-align: center;
  }
  .penalty-controls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .penalty-winner {
    text-align: center; padding: 10px;
    font-size: 15px; font-weight: 700; color: var(--accent);
    background: rgba(48,209,88,0.1); border-radius: 10px; margin-top: 8px;
  }

  /* ── Standings Table ── */
  .standings-table {
    background: var(--bg2); border-radius: 12px; overflow: hidden;
  }
  .st-header {
    display: grid;
    grid-template-columns: 28px 1fr 28px 28px 28px 28px 36px;
    gap: 4px; padding: 8px 12px;
    font-size: 11px; font-weight: 600; color: var(--accent);
    background: rgba(48,209,88,0.08);
    border-bottom: 1px solid var(--border);
  }
  .st-row {
    display: grid;
    grid-template-columns: 28px 1fr 28px 28px 28px 28px 36px;
    gap: 4px; padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    align-items: center;
  }
  .st-row:last-child { border-bottom: none; }
  .st-row:nth-child(even) { background: rgba(255,255,255,0.02); }
  .st-pos { font-size: 13px; color: var(--hint); text-align: center; }
  .st-pos.top { color: var(--accent); font-weight: 700; }
  .st-name { font-weight: 600; font-size: 13px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .st-num { text-align: center; font-size: 13px; color: var(--hint); }
  .st-pts { text-align: center; font-size: 14px; font-weight: 800; color: var(--accent); }
  .st-header span { text-align: center; }
  .st-header span:nth-child(2) { text-align: left; }

  /* ── Rosters ── */
  .roster-card {
    background: var(--bg2); border-radius: 12px;
    padding: 14px 16px; margin-bottom: 12px;
    border: 1px solid var(--border);
  }
  .roster-team-title {
    font-size: 15px; font-weight: 700; margin-bottom: 10px;
    padding-bottom: 8px; border-bottom: 1px solid var(--border);
  }
  .roster-player {
    padding: 6px 0; font-size: 14px; color: var(--text);
    border-bottom: 1px solid var(--border);
  }
  .roster-player:last-child { border-bottom: none; }

  /* ── Footer nav buttons ── */
  .footer-nav {
    margin-top: 16px; display: grid;
    grid-template-columns: 1fr 1fr; gap: 8px;
  }
  .footer-nav-3 {
    margin-top: 16px; display: grid;
    grid-template-columns: 1fr 1fr 1fr; gap: 8px;
  }
</style>
</head>
<body>

<!-- Loading overlay -->
<div class="loading-overlay" id="loadingOverlay"><div class="spinner"></div></div>

<!-- Duration picker (bottom sheet) -->
<div class="dur-overlay" id="durOverlay">
  <div class="dur-sheet">
    <div class="dur-title">⏱ Продолжительность матча</div>
    <div class="dur-grid" id="durGrid">
      <button class="dur-btn" data-min="5"  onclick="selectDur(5)">5 мин</button>
      <button class="dur-btn" data-min="7"  onclick="selectDur(7)">7 мин</button>
      <button class="dur-btn" data-min="8"  onclick="selectDur(8)">8 мин</button>
      <button class="dur-btn" data-min="10" onclick="selectDur(10)">10 мин</button>
      <button class="dur-btn" data-min="12" onclick="selectDur(12)">12 мин</button>
      <button class="dur-btn" data-min="15" onclick="selectDur(15)">15 мин</button>
      <button class="dur-btn" data-min="20" onclick="selectDur(20)">20 мин</button>
      <button class="dur-btn" data-min="25" onclick="selectDur(25)">25 мин</button>
      <button class="dur-btn" data-min="30" onclick="selectDur(30)">30 мин</button>
    </div>
    <div class="dur-custom">
      <input type="number" id="durCustom" placeholder="Другое (мин)" min="1" max="120"
             oninput="selectDurCustom()" />
    </div>
    <div class="action-row">
      <button class="btn btn-neutral" onclick="closeDurPicker()">Отмена</button>
      <button class="btn btn-primary" id="durConfirmBtn" onclick="confirmDur()">▶️ Начать</button>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- VIEW: Match List                           -->
<!-- ═══════════════════════════════════════════ -->
<div class="view" id="viewList">
  <div class="header">
    <div>
      <div class="header-title" id="listTitle">Игровой день</div>
      <div class="header-sub" id="listSub"></div>
    </div>
  </div>
  <div class="content" id="listContent">
    <div class="empty">Загрузка…</div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- VIEW: Match Panel                          -->
<!-- ═══════════════════════════════════════════ -->
<div class="view" id="viewMatch">
  <div class="header">
    <button class="header-back" id="matchBack">← Назад</button>
    <div>
      <div class="header-title" id="matchTitle">Матч</div>
      <div class="header-sub" id="matchSub"></div>
    </div>
  </div>
  <div class="content" id="matchContent">
    <div class="empty">Загрузка…</div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- VIEW: Player Selection                     -->
<!-- ═══════════════════════════════════════════ -->
<div class="view" id="viewPlayers">
  <div class="header">
    <button class="header-back" id="playersBack">← Назад</button>
    <div>
      <div class="header-title" id="playersTitle">Выбор игрока</div>
    </div>
  </div>
  <div class="content" id="playersContent"></div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- VIEW: New Match                            -->
<!-- ═══════════════════════════════════════════ -->
<div class="view" id="viewNewMatch">
  <div class="header">
    <button class="header-back" id="newMatchBack">← Назад</button>
    <div><div class="header-title">Новый матч</div></div>
  </div>
  <div class="content">
    <div class="section">
      <div class="section-title">Команды</div>
      <div style="background:var(--bg2);border-radius:12px;padding:14px;margin-bottom:8px;">
        <div style="margin-bottom:10px;">
          <div style="font-size:12px;color:var(--hint);margin-bottom:6px;">Хозяева</div>
          <select id="nmTeamHome" style="width:100%;padding:10px;border-radius:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);font-size:15px;">
            <option value="">— выбери команду —</option>
          </select>
        </div>
        <div>
          <div style="font-size:12px;color:var(--hint);margin-bottom:6px;">Гости</div>
          <select id="nmTeamAway" style="width:100%;padding:10px;border-radius:8px;background:var(--bg);color:var(--text);border:1px solid var(--border);font-size:15px;">
            <option value="">— выбери команду —</option>
          </select>
        </div>
      </div>
    </div>
    <div class="section">
      <div class="section-title">Стадия</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;" id="nmStageGrid">
        <button class="btn btn-neutral nm-stage-btn" data-stage="group" onclick="selectStage('group')">📋 Группа</button>
        <button class="btn btn-neutral nm-stage-btn" data-stage="semifinal" onclick="selectStage('semifinal')">🏆 Полуфинал</button>
        <button class="btn btn-neutral nm-stage-btn" data-stage="third_place" onclick="selectStage('third_place')">🥉 За 3 место</button>
        <button class="btn btn-neutral nm-stage-btn" data-stage="final" onclick="selectStage('final')">🏆🏆 Финал</button>
      </div>
    </div>
    <div class="action-row" style="margin-top:8px;">
      <button class="btn btn-primary" onclick="createMatch()">➕ Создать матч</button>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- VIEW: Standings                            -->
<!-- ═══════════════════════════════════════════ -->
<div class="view" id="viewStandings">
  <div class="header">
    <button class="header-back" id="standingsBack">← Назад</button>
    <div><div class="header-title">📊 Таблица</div></div>
  </div>
  <div class="content" id="standingsContent">
    <div class="empty">Загрузка…</div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- VIEW: Rosters                              -->
<!-- ═══════════════════════════════════════════ -->
<div class="view" id="viewRosters">
  <div class="header">
    <button class="header-back" id="rostersBack">← Назад</button>
    <div><div class="header-title">👥 Составы команд</div></div>
  </div>
  <div class="content" id="rostersContent">
    <div class="empty">Загрузка…</div>
  </div>
</div>

<script>
Telegram.WebApp.ready();
Telegram.WebApp.expand();

// ── State ─────────────────────────────────────
const state = {
  gameDayId: null,
  matchId: null,
  matchData: null,
  playerMode: null,      // 'goal_home' | 'goal_away' | 'card_home_yellow' | ...
                         // 'sub_out_home' | 'sub_out_away' | 'sub_in_home' | 'sub_in_away'
                         // 'gk_home' | 'gk_away' | 'save'
  playerOutId: null,     // stored during substitution flow (sub_out → sub_in)
  gameDayTeams: [],      // teams list for new match form
  gameDayMatches: [],    // matches list for standings calculation
  listRefreshTimer: null,
  selectedStage: 'group',
  refreshTimer: null,
};

// ── URL params ────────────────────────────────
const params = new URLSearchParams(window.location.search);
state.gameDayId = params.get('gd');

// ── Utils ─────────────────────────────────────
function showLoading(on) {
  document.getElementById('loadingOverlay').classList.toggle('show', on);
}

async function apiFetch(url, options = {}) {
  showLoading(true);
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    const data = await res.json();
    return data;
  } catch(e) {
    Telegram.WebApp.showAlert('Ошибка сети: ' + e.message);
    return null;
  } finally {
    showLoading(false);
  }
}

function fmtTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
}

function elapsedSec(isoStr) {
  if (!isoStr) return 0;
  return Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
}

function fmtCountdown(remainSec) {
  if (remainSec <= 0) return '00:00';
  const m = Math.floor(remainSec / 60);
  const s = remainSec % 60;
  return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
}

// ── Views ─────────────────────────────────────
function showView(id) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = document.getElementById(id);
  el.classList.add('active');
  // Force reflow for transition
  void el.offsetWidth;
}

// ─────────────────────────────────────────────
// VIEW: Match List
// ─────────────────────────────────────────────
async function loadMatchList() {
  if (!state.gameDayId) {
    document.getElementById('listContent').innerHTML =
      '<div class="empty">Игровой день не указан.<br>Откройте страницу через бота.</div>';
    showView('viewList');
    return;
  }
  const data = await apiFetch('/api/referee/gameday/' + state.gameDayId);
  if (!data) return;

  // Store matches for standings calculation
  state.gameDayMatches = data.matches || [];

  document.getElementById('listTitle').textContent = data.game_day.name || 'Игровой день';
  document.getElementById('listSub').textContent =
    (data.game_day.date || '') + (data.game_day.location ? ' · ' + data.game_day.location : '');

  const STAGE_LABELS = {
    group: 'Групповой этап',
    semifinal: 'Полуфинал',
    third_place: 'Матч за 3 место',
    final: 'Финал',
  };

  // Group by stage
  const stages = {};
  for (const m of data.matches) {
    const s = m.stage || 'group';
    if (!stages[s]) stages[s] = [];
    stages[s].push(m);
  }

  const stageOrder = ['group', 'semifinal', 'third_place', 'final'];
  let html = '';

  for (const stageKey of stageOrder) {
    if (!stages[stageKey]) continue;
    html += `<div class="section">
      <div class="section-title">${STAGE_LABELS[stageKey] || stageKey}</div>`;

    for (const m of stages[stageKey]) {
      const statusIcon = m.status === 'finished' ? '✅' : m.status === 'in_progress' ? '▶️' : '⏳';
      const scoreClass = m.status === 'scheduled' ? 'match-list-score scheduled' : 'match-list-score';
      const scoreText = m.status === 'scheduled' ? 'vs' : `${m.score_home}:${m.score_away}`;
      const meta = m.status === 'in_progress' ? 'В процессе' : m.status === 'finished' ? 'Завершён' : 'Запланирован';

      html += `<div class="match-list-card" onclick="openMatch(${m.id})">
        <div class="match-list-status">${statusIcon}</div>
        <div class="match-list-body">
          <div class="match-list-teams">${m.home.emoji} ${m.home.name} — ${m.away.emoji} ${m.away.name}</div>
          <div class="match-list-meta">${meta}</div>
        </div>
        <div class="${scoreClass}">${scoreText}</div>
      </div>`;
    }
    html += '</div>';
  }

  if (!html) html = '<div class="empty">Матчей пока нет</div>';

  // Кнопки внизу
  const gdStatus = data.game_day.status;
  if (gdStatus === 'finished') {
    html += `<div style="margin-top:16px;padding:14px;background:var(--bg2);border-radius:12px;text-align:center;color:var(--accent);font-weight:600;">✅ Игровой день завершён</div>`;
    html += `<div class="footer-nav" style="margin-top:8px;">
      <button class="btn btn-neutral" onclick="loadStandings()">📊 Таблица</button>
      <button class="btn btn-neutral" onclick="loadRosters()">👥 Составы</button>
    </div>`;
  } else {
    html += `<div class="footer-nav-3">
      <button class="btn btn-primary" onclick="openNewMatch()">➕ Новый матч</button>
      <button class="btn btn-neutral" onclick="loadStandings()">📊 Таблица</button>
      <button class="btn btn-neutral" onclick="loadRosters()">👥 Составы</button>
    </div>
    <div style="margin-top:8px;">
      <button class="btn btn-danger" style="width:100%" onclick="finishGameDay()">🏁 Завершить день</button>
    </div>`;
  }

  // Сохраняем команды для формы нового матча
  state.gameDayTeams = data.teams || [];

  document.getElementById('listContent').innerHTML = html;
  showView('viewList');

  // Auto-refresh if any match is live
  if (state.listRefreshTimer) clearTimeout(state.listRefreshTimer);
  const hasLive = (data.matches || []).some(m => m.status === 'in_progress');
  if (hasLive) {
    state.listRefreshTimer = setTimeout(loadMatchList, 30000);
  }
}

// ─────────────────────────────────────────────
// VIEW: Match Panel
// ─────────────────────────────────────────────
async function openMatch(matchId) {
  state.matchId = matchId;
  stopAutoRefresh();
  const data = await apiFetch('/api/referee/match/' + matchId);
  if (!data) return;
  state.matchData = data;
  renderMatch(data);
  showView('viewMatch');
  if (data.status === 'in_progress') {
    startAutoRefresh();
  }
}

function startAutoRefresh() {
  stopAutoRefresh();
  state.refreshTimer = setInterval(async () => {
    if (!state.matchId) return;
    const data = await apiFetch('/api/referee/match/' + state.matchId);
    if (!data) return;
    state.matchData = data;
    // Only re-render match content (not full page)
    renderMatchContent(data);
    if (data.status !== 'in_progress') stopAutoRefresh();
  }, 10000);
}

function stopAutoRefresh() {
  if (state.refreshTimer) {
    clearInterval(state.refreshTimer);
    state.refreshTimer = null;
  }
}

const STAGE_LABELS_PANEL = {
  group: 'Группа',
  semifinal: 'Полуфинал',
  third_place: 'За 3 место',
  final: 'Финал',
};

function renderMatch(data) {
  const stageLabel = STAGE_LABELS_PANEL[data.stage] || data.stage || '';
  document.getElementById('matchTitle').textContent =
    stageLabel ? `${stageLabel} · Матч ${data.order}` : `Матч ${data.order}`;
  document.getElementById('matchSub').textContent =
    `${data.home.emoji} ${data.home.name} vs ${data.away.emoji} ${data.away.name}`;
  renderMatchContent(data);
}

function renderMatchContent(data) {
  const el = document.getElementById('matchContent');
  el.innerHTML = buildMatchHTML(data);
  // Start live countdown timer if in progress
  if (data.status === 'in_progress' && data.started_at) {
    startLiveTimer(data.started_at, data.duration_minutes || 0);
  }
}

let _timerInterval = null;
function startLiveTimer(startedAt, durationMin) {
  if (_timerInterval) clearInterval(_timerInterval);
  const totalSec = (durationMin || 0) * 60;
  function tick() {
    const elapsed = elapsedSec(startedAt);
    const el = document.getElementById('liveTimer');
    if (!el) return;
    if (totalSec > 0) {
      // Обратный отсчёт
      const remain = totalSec - elapsed;
      el.textContent = fmtCountdown(Math.max(0, remain));
      // Красный цвет когда время вышло
      el.style.color = remain <= 0 ? 'var(--danger)' : 'var(--accent)';
      // Текст "ВРЕМЯ!" рядом
      const overEl = document.getElementById('timerOver');
      if (overEl) overEl.style.display = remain <= 0 ? 'inline' : 'none';
    } else {
      // Нет длительности — показываем elapsed (запасной вариант)
      const m = Math.floor(elapsed / 60);
      const s = elapsed % 60;
      el.textContent = String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
    }
  }
  tick();
  _timerInterval = setInterval(tick, 1000);
}

function buildMatchHTML(data) {
  const isScheduled = data.status === 'scheduled';
  const isInProgress = data.status === 'in_progress';
  const isFinished = data.status === 'finished';

  let timerHTML = '';
  if (isInProgress && data.started_at) {
    const durMin = data.duration_minutes || 0;
    const durLabel = durMin ? `${durMin} мин` : '';
    timerHTML = `<div style="margin-top:8px;text-align:center;">
      <div class="timer-row" style="justify-content:center;">
        <span style="font-size:20px;">⏱</span>
        <span class="timer-live" id="liveTimer">--:--</span>
        <span id="timerOver" style="display:none;color:var(--danger);font-weight:700;font-size:22px;">ВРЕМЯ!</span>
      </div>
      <div style="margin-top:4px;display:flex;align-items:center;justify-content:center;gap:8px;">
        <span style="color:var(--hint);font-size:12px;">${durLabel}</span>
        <button onclick="extendTime()" style="background:var(--bg);border:1px solid var(--border);color:var(--hint);border-radius:8px;padding:2px 10px;font-size:12px;cursor:pointer;">+30с</button>
      </div>
    </div>`;
  } else if (isFinished) {
    timerHTML = `<div class="timer-row">✅ Завершён</div>`;
  } else {
    timerHTML = `<div class="timer-row" style="color:var(--hint)">⏳ Запланирован</div>`;
  }

  // GK info rows under scoreboard
  const homeGkLabel = data.home_gk
    ? `🧤 ${data.home_gk.player_name} (${data.home_gk.saves} сейв${pluralSaves(data.home_gk.saves)})`
    : '🧤 Вратарь не назначен';
  const awayGkLabel = data.away_gk
    ? `🧤 ${data.away_gk.player_name} (${data.away_gk.saves} сейв${pluralSaves(data.away_gk.saves)})`
    : '🧤 Вратарь не назначен';

  let html = `
  <div class="score-board">
    <div class="score-teams">
      <div class="score-team-name home">${data.home.emoji} ${data.home.name}</div>
      <div class="score-digits">${data.score_home}:${data.score_away}</div>
      <div class="score-team-name away">${data.away.emoji} ${data.away.name}</div>
    </div>
    ${timerHTML}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:8px;font-size:12px;color:var(--hint);">
      <div style="text-align:right;">${homeGkLabel}</div>
      <div style="text-align:left;">${awayGkLabel}</div>
    </div>
  </div>`;

  // Penalty shootout section
  const penaltyStages = ['semifinal', 'third_place', 'final'];
  if (isFinished && data.score_home === data.score_away && penaltyStages.includes(data.stage)) {
    if (data.penalty) {
      // Show penalty scoreboard
      const ps = data.penalty;
      let penaltyContent = `
      <div class="penalty-title">🥅 СЕРИЯ ПЕНАЛЬТИ</div>
      <div class="penalty-score">
        <div class="penalty-team">${data.home.emoji} ${data.home.name}</div>
        <div class="penalty-digits">${ps.score_home} : ${ps.score_away}</div>
        <div class="penalty-team">${data.away.emoji} ${data.away.name}</div>
      </div>`;
      if (ps.finished) {
        const winnerName = ps.winner_team_id === data.home.id
          ? `${data.home.emoji} ${data.home.name}`
          : `${data.away.emoji} ${data.away.name}`;
        penaltyContent += `<div class="penalty-winner">🏆 Победил — ${winnerName}</div>`;
      } else {
        penaltyContent += `<div class="penalty-controls">
          <button class="btn btn-neutral" style="font-size:13px;" onclick="penaltyKick('home', true)">⚽ Гол Хозяева</button>
          <button class="btn btn-neutral" style="font-size:13px;" onclick="penaltyKick('away', true)">⚽ Гол Гости</button>
          <button class="btn btn-neutral" style="font-size:13px;" onclick="penaltyKick('home', false)">❌ Промах Хозяева</button>
          <button class="btn btn-neutral" style="font-size:13px;" onclick="penaltyKick('away', false)">❌ Промах Гости</button>
        </div>
        <div class="action-row" style="margin-top:8px;">
          <button class="btn btn-neutral" style="font-size:13px;" onclick="penaltyFinish('home')">🏆 Победил — Хозяева</button>
          <button class="btn btn-neutral" style="font-size:13px;" onclick="penaltyFinish('away')">🏆 Победил — Гости</button>
        </div>`;
      }
      html += `<div class="penalty-panel">${penaltyContent}</div>`;
    } else {
      // Show "start penalty" button
      html += `<div class="action-row">
        <button class="btn btn-neutral" onclick="startPenalty()">🥅 Серия пенальти</button>
      </div>`;
    }
  }

  // Score +/- controls (only when not scheduled)
  if (!isScheduled) {
    html += `<div class="score-controls">
      <div class="score-side home">
        <button class="score-btn minus" onclick="removeLastGoal(${data.home.id}, '${data.home.name}')">−</button>
        <button class="score-btn plus" onclick="openPlayerSelect('goal_home')">+</button>
      </div>
      <div class="score-side away">
        <button class="score-btn plus" onclick="openPlayerSelect('goal_away')">+</button>
        <button class="score-btn minus" onclick="removeLastGoal(${data.away.id}, '${data.away.name}')">−</button>
      </div>
    </div>`;
  }

  // Main action buttons
  html += `<div class="action-row">`;
  if (isScheduled) {
    html += `<button class="btn btn-primary" onclick="startMatch()">▶️ Начать матч</button>`;
  } else if (isInProgress) {
    html += `<button class="btn btn-danger" onclick="finishMatch()">🏁 Завершить матч</button>`;
  } else {
    html += `<button class="btn btn-disabled" disabled>✅ Завершён</button>`;
  }
  html += `</div>`;

  // Substitution button (in_progress only)
  if (isInProgress) {
    html += `<div class="action-row">
      <button class="btn btn-neutral" onclick="openPlayerSelect('sub_out_home')">🔄 Замена ${data.home.emoji}</button>
      <button class="btn btn-neutral" onclick="openPlayerSelect('sub_out_away')">🔄 Замена ${data.away.emoji}</button>
    </div>`;
  }

  // Goalkeeper assignment buttons
  if (!isFinished) {
    html += `<div class="action-row">
      <button class="btn btn-neutral" onclick="openPlayerSelect('gk_home')">🧤 ВРТ ${data.home.emoji}</button>
      <button class="btn btn-neutral" onclick="openPlayerSelect('gk_away')">🧤 ВРТ ${data.away.emoji}</button>
    </div>`;
  }

  // Save button (only if at least one GK assigned and match not scheduled)
  if (!isScheduled && (data.home_gk || data.away_gk)) {
    html += `<div class="action-row">`;
    if (data.home_gk) {
      html += `<button class="btn btn-neutral" onclick="recordSave(${data.home.id})">🛡 Сейв ${data.home.emoji}</button>`;
    }
    if (data.away_gk) {
      html += `<button class="btn btn-neutral" onclick="recordSave(${data.away.id})">🛡 Сейв ${data.away.emoji}</button>`;
    }
    html += `</div>`;
  }

  // Card buttons
  if (!isScheduled) {
    html += `<div class="action-row">
      <button class="btn btn-yellow" onclick="openPlayerSelect('card_home_yellow')">🟨 ЖК ${data.home.name}</button>
      <button class="btn btn-yellow" onclick="openPlayerSelect('card_away_yellow')">🟨 ЖК ${data.away.name}</button>
    </div>
    <div class="action-row">
      <button class="btn btn-red" onclick="openPlayerSelect('card_home_red')">🟥 КК ${data.home.name}</button>
      <button class="btn btn-red" onclick="openPlayerSelect('card_away_red')">🟥 КК ${data.away.name}</button>
    </div>`;
  }

  // Events
  const events = buildEvents(data);
  html += `<div class="section" style="margin-top:16px">
    <div class="section-title">События матча</div>`;
  if (events.length === 0) {
    html += `<div class="empty">Событий пока нет</div>`;
  } else {
    html += `<div class="events-list">`;
    for (const ev of events) {
      const delBtn = ev.goalId
        ? `<button class="event-del" onclick="deleteGoal(${ev.goalId})" title="Удалить">✕</button>`
        : '';
      html += `<div class="event-item">
        <div class="event-icon">${ev.icon}</div>
        <div class="event-body">
          <div class="event-player">${ev.player}</div>
          <div class="event-meta">${ev.meta}</div>
        </div>
        ${delBtn}
      </div>`;
    }
    html += `</div>`;
  }
  html += `</div>`;

  return html;
}

function pluralSaves(n) {
  if (n % 10 === 1 && n % 100 !== 11) return '';
  if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) return 'а';
  return 'ов';
}

function buildEvents(data) {
  const events = [];
  for (const g of (data.goals || [])) {
    const teamName = g.team_id === data.home.id ? data.home.name : data.away.name;
    events.push({
      icon: g.own_goal ? '⚽↩️' : '⚽',
      player: g.player_name + (g.own_goal ? ' (автогол)' : ''),
      meta: teamName + (g.scored_at ? ' · ' + fmtTime(g.scored_at) : ''),
      goalId: g.id,
    });
  }
  for (const c of (data.cards || [])) {
    const teamName = c.team_id === data.home.id ? data.home.name : data.away.name;
    events.push({
      icon: c.card_type === 'yellow' ? '🟨' : '🟥',
      player: c.player_name,
      meta: teamName + (c.issued_at ? ' · ' + fmtTime(c.issued_at) : ''),
      goalId: null,
    });
  }
  return events;
}

// ─────────────────────────────────────────────
// VIEW: Player Selection
// ─────────────────────────────────────────────
function openPlayerSelect(mode) {
  if (!state.matchData) return;
  state.playerMode = mode;
  const data = state.matchData;

  const isHome = mode.includes('_home');
  const team = isHome ? data.home : data.away;
  const isGoal = mode.startsWith('goal');
  const isCard = mode.startsWith('card');
  const isSubOut = mode.startsWith('sub_out');
  const isSubIn = mode.startsWith('sub_in');
  const isGk = mode.startsWith('gk');

  let title = '';
  let players = [];
  let html = '';

  if (isGoal) {
    title = `Кто забил? (${team.emoji} ${team.name})`;
    players = isHome ? (data.home_players || []) : (data.away_players || []);
    html += `<button class="own-goal-btn" onclick="recordGoal(null, true)">⚽↩️ Автогол</button>`;
    html += `<div class="player-grid">`;
    for (const p of players) {
      html += `<button class="player-btn" onclick="recordGoal(${p.id})">${p.name}</button>`;
    }
    html += `</div>`;
    if (!players.length) html += `<div class="empty">Нет игроков в составе</div>`;

  } else if (isCard) {
    title = `Кто получил карточку? (${team.emoji} ${team.name})`;
    players = isHome ? (data.home_players || []) : (data.away_players || []);
    html += `<div class="player-grid">`;
    for (const p of players) {
      html += `<button class="player-btn" onclick="recordCard(${p.id})">${p.name}</button>`;
    }
    html += `</div>`;
    if (!players.length) html += `<div class="empty">Нет игроков в составе</div>`;

  } else if (isSubOut) {
    title = `Кто выходит? (${team.emoji} ${team.name})`;
    players = isHome ? (data.home_players || []) : (data.away_players || []);
    html += `<div class="player-grid">`;
    for (const p of players) {
      html += `<button class="player-btn" onclick="pickSubOut(${p.id})">${p.name}</button>`;
    }
    html += `</div>`;
    if (!players.length) html += `<div class="empty">Нет игроков в составе</div>`;

  } else if (isSubIn) {
    title = `Кто заходит?`;
    // bench players + opposite team players (marked with *)
    const benchPlayers = data.bench_players || [];
    const otherPlayers = isHome ? (data.away_players || []) : (data.home_players || []);
    html += `<div class="player-grid">`;
    for (const p of benchPlayers) {
      html += `<button class="player-btn" onclick="pickSubIn(${p.id})">${p.name}</button>`;
    }
    for (const p of otherPlayers) {
      html += `<button class="player-btn" style="opacity:0.7" onclick="pickSubIn(${p.id})">${p.name} *</button>`;
    }
    html += `</div>`;
    if (!benchPlayers.length && !otherPlayers.length) html += `<div class="empty">Нет доступных игроков</div>`;

  } else if (isGk) {
    title = `Назначить вратаря (${team.emoji} ${team.name})`;
    players = isHome ? (data.home_players || []) : (data.away_players || []);
    html += `<div class="player-grid">`;
    for (const p of players) {
      html += `<button class="player-btn" onclick="assignGoalkeeper(${p.id})">${p.name}</button>`;
    }
    html += `</div>`;
    if (!players.length) html += `<div class="empty">Нет игроков в составе</div>`;
  }

  document.getElementById('playersTitle').textContent = title;
  document.getElementById('playersContent').innerHTML = html;
  showView('viewPlayers');
}

// ─────────────────────────────────────────────
// Actions
// ─────────────────────────────────────────────
// ── Duration picker ───────────────────────────
let _selectedDur = null;

function startMatch() {
  // Показать picker вместо немедленного старта
  _selectedDur = state.matchData ? (state.matchData.duration_minutes || 10) : 10;
  // Подсветить текущее значение
  document.querySelectorAll('.dur-btn').forEach(b => {
    const v = parseInt(b.dataset.min);
    b.classList.toggle('selected', v === _selectedDur);
  });
  document.getElementById('durCustom').value = '';
  document.getElementById('durOverlay').classList.add('show');
}

function selectDur(min) {
  _selectedDur = min;
  document.querySelectorAll('.dur-btn').forEach(b =>
    b.classList.toggle('selected', parseInt(b.dataset.min) === min)
  );
  document.getElementById('durCustom').value = '';
}

function selectDurCustom() {
  const v = parseInt(document.getElementById('durCustom').value);
  if (v > 0) {
    _selectedDur = v;
    document.querySelectorAll('.dur-btn').forEach(b => b.classList.remove('selected'));
  }
}

function closeDurPicker() {
  document.getElementById('durOverlay').classList.remove('show');
}

async function confirmDur() {
  if (!_selectedDur || _selectedDur < 1) {
    Telegram.WebApp.showAlert('Выбери продолжительность!');
    return;
  }
  closeDurPicker();
  const ok = await apiFetch('/api/referee/match/' + state.matchId + '/start', {
    method: 'POST',
    body: JSON.stringify({ duration_min: _selectedDur }),
  });
  if (ok) await refreshMatch();
}

async function finishMatch() {
  Telegram.WebApp.showConfirm('Завершить матч?', async (confirmed) => {
    if (!confirmed) return;
    const ok = await apiFetch('/api/referee/match/' + state.matchId + '/finish', { method: 'POST' });
    if (ok) await refreshMatch();
  });
}

async function recordGoal(playerId, ownGoal = false) {
  const mode = state.playerMode;
  const data = state.matchData;
  const isHome = mode && mode.includes('_home');
  const teamId = isHome ? data.home.id : data.away.id;

  const body = { player_id: playerId, team_id: teamId, own_goal: ownGoal };
  const res = await apiFetch('/api/referee/match/' + state.matchId + '/goal', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (res && res.ok) {
    await refreshMatch();
    showView('viewMatch');
  }
}

async function recordCard(playerId) {
  const mode = state.playerMode;
  const data = state.matchData;
  const isHome = mode && mode.includes('_home');
  const teamId = isHome ? data.home.id : data.away.id;
  const cardType = mode && mode.includes('_red') ? 'red' : 'yellow';

  const body = { player_id: playerId, team_id: teamId, card_type: cardType };
  const res = await apiFetch('/api/referee/match/' + state.matchId + '/card', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (res && res.ok) {
    await refreshMatch();
    showView('viewMatch');
  }
}

async function deleteGoal(goalId) {
  Telegram.WebApp.showConfirm('Удалить этот гол?', async (confirmed) => {
    if (!confirmed) return;
    const res = await apiFetch('/api/referee/goal/' + goalId, { method: 'DELETE' });
    if (res && res.ok) {
      await refreshMatch();
    }
  });
}

async function removeLastGoal(teamId, teamName) {
  const data = state.matchData;
  if (!data) return;
  // Find last goal of this team
  const teamGoals = (data.goals || []).filter(g => g.team_id === teamId);
  if (!teamGoals.length) {
    Telegram.WebApp.showAlert('У команды «' + teamName + '» нет голов для удаления.');
    return;
  }
  const lastGoal = teamGoals[teamGoals.length - 1];
  Telegram.WebApp.showConfirm(`Удалить последний гол команды «${teamName}»?`, async (confirmed) => {
    if (!confirmed) return;
    const res = await apiFetch('/api/referee/goal/' + lastGoal.id, { method: 'DELETE' });
    if (res && res.ok) await refreshMatch();
  });
}

async function refreshMatch() {
  const data = await apiFetch('/api/referee/match/' + state.matchId);
  if (!data) return;
  state.matchData = data;
  renderMatchContent(data);
  if (data.status === 'in_progress') {
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }
}

// ─────────────────────────────────────────────
// Substitution
// ─────────────────────────────────────────────
function pickSubOut(playerId) {
  state.playerOutId = playerId;
  // Switch to sub_in mode for same team
  const isHome = state.playerMode === 'sub_out_home';
  openPlayerSelect(isHome ? 'sub_in_home' : 'sub_in_away');
}

async function pickSubIn(playerInId) {
  const mode = state.playerMode;
  const data = state.matchData;
  const isHome = mode === 'sub_in_home';
  const teamId = isHome ? data.home.id : data.away.id;

  const res = await apiFetch('/api/referee/match/' + state.matchId + '/sub', {
    method: 'POST',
    body: JSON.stringify({
      team_id: teamId,
      player_out_id: state.playerOutId,
      player_in_id: playerInId,
    }),
  });
  if (res && res.ok) {
    state.playerOutId = null;
    await refreshMatch();
    showView('viewMatch');
  }
}

// ─────────────────────────────────────────────
// Goalkeeper
// ─────────────────────────────────────────────
async function assignGoalkeeper(playerId) {
  const mode = state.playerMode;
  const data = state.matchData;
  const isHome = mode === 'gk_home';
  const teamId = isHome ? data.home.id : data.away.id;

  const res = await apiFetch('/api/referee/match/' + state.matchId + '/goalkeeper', {
    method: 'POST',
    body: JSON.stringify({ team_id: teamId, player_id: playerId }),
  });
  if (res && res.ok) {
    await refreshMatch();
    showView('viewMatch');
  }
}

// ─────────────────────────────────────────────
// Save
// ─────────────────────────────────────────────
async function recordSave(teamId) {
  const res = await apiFetch('/api/referee/match/' + state.matchId + '/save', {
    method: 'POST',
    body: JSON.stringify({ team_id: teamId }),
  });
  if (res && res.ok) {
    await refreshMatch();
  }
}

// ─────────────────────────────────────────────
// New Match
// ─────────────────────────────────────────────
function openNewMatch() {
  const teams = state.gameDayTeams;
  if (!teams || teams.length < 2) {
    Telegram.WebApp.showAlert('Нет команд для создания матча. Сначала создайте команды через бота.');
    return;
  }

  // Заполнить селекты командами
  const homeSelect = document.getElementById('nmTeamHome');
  const awaySelect = document.getElementById('nmTeamAway');
  homeSelect.innerHTML = '<option value="">— хозяева —</option>';
  awaySelect.innerHTML = '<option value="">— гости —</option>';
  teams.forEach(t => {
    homeSelect.innerHTML += `<option value="${t.id}">${t.emoji} ${t.name}</option>`;
    awaySelect.innerHTML += `<option value="${t.id}">${t.emoji} ${t.name}</option>`;
  });

  // Сбросить стадию на «группа»
  state.selectedStage = 'group';
  document.querySelectorAll('.nm-stage-btn').forEach(b => {
    b.classList.toggle('btn-primary', b.dataset.stage === 'group');
    b.classList.toggle('btn-neutral', b.dataset.stage !== 'group');
  });

  showView('viewNewMatch');
}

function selectStage(stage) {
  state.selectedStage = stage;
  document.querySelectorAll('.nm-stage-btn').forEach(b => {
    b.classList.toggle('btn-primary', b.dataset.stage === stage);
    b.classList.toggle('btn-neutral', b.dataset.stage !== stage);
  });
}

async function createMatch() {
  const homeId = parseInt(document.getElementById('nmTeamHome').value);
  const awayId = parseInt(document.getElementById('nmTeamAway').value);

  if (!homeId || !awayId) {
    Telegram.WebApp.showAlert('Выбери обе команды!');
    return;
  }
  if (homeId === awayId) {
    Telegram.WebApp.showAlert('Хозяева и гости должны быть разными командами!');
    return;
  }

  const body = {
    team_home_id: homeId,
    team_away_id: awayId,
    stage: state.selectedStage,
  };
  const res = await apiFetch('/api/referee/gameday/' + state.gameDayId + '/new_match', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (res && res.ok) {
    Telegram.WebApp.showAlert('✅ Матч создан!');
    await loadMatchList();
  }
}

// ─────────────────────────────────────────────
// Penalty Shootout
// ─────────────────────────────────────────────
async function startPenalty() {
  const res = await apiFetch('/api/referee/match/' + state.matchId + '/penalty/start', { method: 'POST' });
  if (res && res.ok) await refreshMatch();
}

async function penaltyKick(side, scored) {
  const res = await apiFetch('/api/referee/match/' + state.matchId + '/penalty/kick', {
    method: 'POST',
    body: JSON.stringify({ side, scored }),
  });
  if (res && res.ok) await refreshMatch();
}

async function penaltyFinish(winner) {
  Telegram.WebApp.showConfirm(`Объявить победителем: ${winner === 'home' ? 'Хозяева' : 'Гости'}?`, async (confirmed) => {
    if (!confirmed) return;
    const res = await apiFetch('/api/referee/match/' + state.matchId + '/penalty/finish', {
      method: 'POST',
      body: JSON.stringify({ winner }),
    });
    if (res && res.ok) await refreshMatch();
  });
}

// ─────────────────────────────────────────────
// Extend time (+30s)
// ─────────────────────────────────────────────
async function extendTime() {
  const res = await apiFetch('/api/referee/match/' + state.matchId + '/extend', {
    method: 'POST',
    body: JSON.stringify({ seconds: 30 }),
  });
  if (res && res.ok) await refreshMatch();
}

// ─────────────────────────────────────────────
// Standings
// ─────────────────────────────────────────────
function loadStandings() {
  const matches = state.gameDayMatches || [];
  const teams = state.gameDayTeams || [];

  // Build team name/emoji map
  const teamMap = {};
  for (const t of teams) {
    teamMap[t.id] = { name: t.name, emoji: t.emoji };
  }

  // Calculate standings from finished group-stage matches
  const stats = {};
  for (const m of matches) {
    if (m.status !== 'finished' || m.stage !== 'group') continue;
    const sides = [
      { id: m.home.id, gf: m.score_home, ga: m.score_away },
      { id: m.away.id, gf: m.score_away, ga: m.score_home },
    ];
    for (const { id, gf, ga } of sides) {
      if (!stats[id]) {
        const t = m.home.id === id ? m.home : m.away;
        stats[id] = { name: t.name, emoji: t.emoji, gp: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0 };
      }
      const s = stats[id];
      s.gp++; s.gf += gf; s.ga += ga;
      if (gf > ga) s.w++;
      else if (gf === ga) s.d++;
      else s.l++;
    }
  }

  // Also include teams that haven't played yet
  for (const t of teams) {
    if (!stats[t.id]) {
      stats[t.id] = { name: t.name, emoji: t.emoji, gp: 0, w: 0, d: 0, l: 0, gf: 0, ga: 0 };
    }
  }

  for (const s of Object.values(stats)) {
    s.pts = s.w * 3 + s.d;
    s.gd = s.gf - s.ga;
  }

  const sorted = Object.values(stats).sort((a, b) =>
    b.pts - a.pts || b.gd - a.gd || b.gf - a.gf
  );

  let html = '';
  if (sorted.length === 0) {
    html = '<div class="empty">Нет данных для таблицы</div>';
  } else {
    html += `<div class="standings-table">
      <div class="st-header">
        <span>#</span><span>Команда</span>
        <span>И</span><span>В</span><span>Н</span><span>П</span><span>О</span>
      </div>`;
    sorted.forEach((s, i) => {
      const posClass = i < 2 ? 'st-pos top' : 'st-pos';
      html += `<div class="st-row">
        <span class="${posClass}">${i + 1}</span>
        <span class="st-name">${s.emoji} ${s.name}</span>
        <span class="st-num">${s.gp}</span>
        <span class="st-num">${s.w}</span>
        <span class="st-num">${s.d}</span>
        <span class="st-num">${s.l}</span>
        <span class="st-pts">${s.pts}</span>
      </div>`;
    });
    html += `</div>`;
  }

  document.getElementById('standingsContent').innerHTML = html;
  showView('viewStandings');
}

// ─────────────────────────────────────────────
// Rosters
// ─────────────────────────────────────────────
async function loadRosters() {
  if (!state.gameDayId) return;
  const data = await apiFetch('/api/referee/gameday/' + state.gameDayId + '/rosters');
  if (!data) return;

  const teams = data.teams || [];
  let html = '';
  if (teams.length === 0) {
    html = '<div class="empty">Нет команд</div>';
  } else {
    for (const team of teams) {
      html += `<div class="roster-card">
        <div class="roster-team-title">${team.emoji} ${team.name}</div>`;
      if (!team.players || team.players.length === 0) {
        html += `<div style="color:var(--hint);font-size:13px;">Нет игроков</div>`;
      } else {
        for (const p of team.players) {
          html += `<div class="roster-player">${p.name}</div>`;
        }
      }
      html += `</div>`;
    }
  }

  document.getElementById('rostersContent').innerHTML = html;
  showView('viewRosters');
}

// ─────────────────────────────────────────────
// Finish game day
// ─────────────────────────────────────────────
async function finishGameDay() {
  Telegram.WebApp.showConfirm('Завершить игровой день? Это действие нельзя отменить.', async (confirmed) => {
    if (!confirmed) return;
    const res = await apiFetch('/api/referee/gameday/' + state.gameDayId + '/finish', { method: 'POST' });
    if (res && res.ok) {
      await loadMatchList();
    }
  });
}

// ─────────────────────────────────────────────
// Back navigation
// ─────────────────────────────────────────────
document.getElementById('matchBack').addEventListener('click', () => {
  stopAutoRefresh();
  if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
  loadMatchList();
});

document.getElementById('newMatchBack').addEventListener('click', () => {
  loadMatchList();
});

document.getElementById('standingsBack').addEventListener('click', () => {
  loadMatchList();
});

document.getElementById('rostersBack').addEventListener('click', () => {
  loadMatchList();
});

document.getElementById('playersBack').addEventListener('click', () => {
  // If we are in sub_in step, go back to sub_out step so user can re-pick
  if (state.playerMode === 'sub_in_home' || state.playerMode === 'sub_in_away') {
    state.playerOutId = null;
    openPlayerSelect(state.playerMode === 'sub_in_home' ? 'sub_out_home' : 'sub_out_away');
  } else {
    showView('viewMatch');
  }
});

// ─────────────────────────────────────────────
// Init
// ─────────────────────────────────────────────
loadMatchList();
</script>
</body>
</html>"""


# ─── REFEREE API ──────────────────────────────────────────────────────────────

_STAGE_LABELS = {
    "group": "Групповой этап",
    "semifinal": "Полуфинал",
    "third_place": "За 3-е место",
    "final": "Финал",
}


async def referee_page(request: web.Request) -> web.Response:
    return web.Response(text=_REFEREE_HTML, content_type="text/html")


async def api_referee_gameday(request: web.Request) -> web.Response:
    """GET /api/referee/gameday/{game_day_id}"""
    game_day_id = int(request.match_info["game_day_id"])

    async with AsyncSessionFactory() as session:
        gd_result = await session.execute(
            select(GameDay).where(GameDay.id == game_day_id)
        )
        game_day = gd_result.scalar_one_or_none()
        if not game_day:
            raise web.HTTPNotFound(reason="GameDay not found")

        matches_result = await session.execute(
            select(Match)
            .options(selectinload(Match.team_home), selectinload(Match.team_away))
            .where(Match.game_day_id == game_day_id)
            .order_by(Match.match_order, Match.id)
        )
        matches = matches_result.scalars().all()

        matches_data = []
        for m in matches:
            matches_data.append({
                "id": m.id,
                "stage": m.match_stage or "group",
                "order": getattr(m, "match_order", 0) or 0,
                "home": {
                    "id": m.team_home.id,
                    "name": m.team_home.name,
                    "emoji": m.team_home.color_emoji,
                },
                "away": {
                    "id": m.team_away.id,
                    "name": m.team_away.name,
                    "emoji": m.team_away.color_emoji,
                },
                "score_home": m.score_home,
                "score_away": m.score_away,
                "status": m.status.value,
                "started_at": (m.started_at.isoformat() + "Z") if m.started_at else None,
            })

        # Команды игрового дня для формы «Новый матч»
        teams_res = await session.execute(
            select(Team).where(Team.game_day_id == game_day_id).order_by(Team.id)
        )
        teams_data = [
            {"id": t.id, "name": t.name, "emoji": t.color_emoji or "⚽"}
            for t in teams_res.scalars().all()
        ]

        return web.json_response({
            "game_day": {
                "id": game_day.id,
                "name": game_day.display_name,
                "date": game_day.scheduled_at.strftime("%d.%m.%Y"),
                "location": game_day.location,
                "status": game_day.status.value,
            },
            "matches": matches_data,
            "teams": teams_data,
        })


async def api_referee_match(request: web.Request) -> web.Response:
    """GET /api/referee/match/{match_id}"""
    match_id = int(request.match_info["match_id"])

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Match)
            .options(
                selectinload(Match.team_home).selectinload(Team.players).selectinload(TeamPlayer.player),
                selectinload(Match.team_away).selectinload(Team.players).selectinload(TeamPlayer.player),
                selectinload(Match.goals).selectinload(Goal.player),
                selectinload(Match.cards).selectinload(Card.player),
            )
            .where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        def player_list(team: Team):
            return [
                {"id": tp.player.id, "name": tp.player.name}
                for tp in (team.players or [])
                if tp.player
            ]

        goals_data = []
        for g in sorted(match.goals, key=lambda x: x.scored_at):
            goals_data.append({
                "id": g.id,
                "player_name": g.player.name if g.player else "—",
                "team_id": g.team_id,
                "own_goal": g.goal_type == GoalType.OWN_GOAL,
                "scored_at": (g.scored_at.isoformat() + "Z") if g.scored_at else None,
            })

        cards_data = []
        for c in sorted(match.cards, key=lambda x: x.issued_at):
            cards_data.append({
                "id": c.id,
                "player_name": c.player.name if c.player else "—",
                "team_id": c.team_id,
                "card_type": c.card_type.value,
                "issued_at": (c.issued_at.isoformat() + "Z") if c.issued_at else None,
            })

        # Goalkeepers for this match
        gk_result = await session.execute(
            select(MatchGoalkeeper)
            .options(selectinload(MatchGoalkeeper.player))
            .where(MatchGoalkeeper.match_id == match_id)
        )
        gk_rows = gk_result.scalars().all()
        home_gk_data = None
        away_gk_data = None
        for gk in gk_rows:
            gk_info = {
                "player_id": gk.player_id,
                "player_name": gk.player.name if gk.player else "—",
                "saves": gk.saves,
            }
            if gk.team_id == match.team_home_id:
                home_gk_data = gk_info
            elif gk.team_id == match.team_away_id:
                away_gk_data = gk_info

        # Bench players: attendees NOT in either team roster
        home_player_ids = {tp.player_id for tp in (match.team_home.players or []) if tp.player_id}
        away_player_ids = {tp.player_id for tp in (match.team_away.players or []) if tp.player_id}
        in_team_ids = home_player_ids | away_player_ids

        att_result = await session.execute(
            select(Attendance)
            .options(selectinload(Attendance.player))
            .where(
                Attendance.game_day_id == match.game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        attendances = att_result.scalars().all()
        bench_players = [
            {"id": a.player.id, "name": a.player.name}
            for a in attendances
            if a.player and a.player.id not in in_team_ids
        ]

        # Load penalty shootout
        ps_res = await session.execute(
            select(PenaltyShootout).where(PenaltyShootout.match_id == match_id)
        )
        ps = ps_res.scalar_one_or_none()
        penalty_data = None
        if ps:
            penalty_data = {
                "score_home": ps.score_home,
                "score_away": ps.score_away,
                "finished": ps.finished,
                "winner_team_id": ps.winner_team_id,
            }

        return web.json_response({
            "id": match.id,
            "stage": match.match_stage or "group",
            "order": getattr(match, "match_order", 0) or 0,
            "home": {
                "id": match.team_home.id,
                "name": match.team_home.name,
                "emoji": match.team_home.color_emoji,
            },
            "away": {
                "id": match.team_away.id,
                "name": match.team_away.name,
                "emoji": match.team_away.color_emoji,
            },
            "score_home": match.score_home,
            "score_away": match.score_away,
            "status": match.status.value,
            "started_at": (match.started_at.isoformat() + "Z") if match.started_at else None,
            "format": match.match_format.value if match.match_format else "time",
            "duration_minutes": match.duration_min,
            "goals": goals_data,
            "cards": cards_data,
            "home_players": player_list(match.team_home),
            "away_players": player_list(match.team_away),
            "bench_players": bench_players,
            "home_gk": home_gk_data,
            "away_gk": away_gk_data,
            "penalty": penalty_data,
        })


async def api_referee_start(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/start"""
    match_id = int(request.match_info["match_id"])

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        match.status = MatchStatus.IN_PROGRESS
        match.started_at = datetime.now()
        # Если рефери выбрал продолжительность — сохраняем
        if "duration_min" in body and body["duration_min"]:
            try:
                match.duration_min = int(body["duration_min"])
            except (ValueError, TypeError):
                pass
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_finish(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/finish"""
    match_id = int(request.match_info["match_id"])

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        match.status = MatchStatus.FINISHED
        match.finished_at = datetime.now()
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_goal(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/goal"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    player_id = body.get("player_id")
    team_id = int(body["team_id"])
    own_goal = bool(body.get("own_goal", False))

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        # Determine goal type
        goal_type = GoalType.OWN_GOAL if own_goal else GoalType.GOAL

        # For own goal: the team_id is the team that scored against themselves,
        # so the goal counts for the opposing team's score.
        # The goal record stores team_id = team of the player who scored the own goal.
        goal = Goal(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            goal_type=goal_type,
            scored_at=datetime.now(),
        )
        session.add(goal)

        # Update score: own goal counts for the other team
        if own_goal:
            if team_id == match.team_home_id:
                match.score_away += 1
            else:
                match.score_home += 1
        else:
            if team_id == match.team_home_id:
                match.score_home += 1
            else:
                match.score_away += 1

        await session.commit()

        return web.json_response({
            "ok": True,
            "score_home": match.score_home,
            "score_away": match.score_away,
        })


async def api_referee_card(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/card"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    player_id = int(body["player_id"])
    team_id = int(body["team_id"])
    card_type_str = body.get("card_type", "yellow")
    card_type = CardType.RED if card_type_str == "red" else CardType.YELLOW

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        card = Card(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            card_type=card_type,
            issued_at=datetime.now(),
        )
        session.add(card)
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_delete_goal(request: web.Request) -> web.Response:
    """DELETE /api/referee/goal/{goal_id}"""
    goal_id = int(request.match_info["goal_id"])

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Goal).where(Goal.id == goal_id))
        goal = result.scalar_one_or_none()
        if not goal:
            raise web.HTTPNotFound(reason="Goal not found")

        match_result = await session.execute(select(Match).where(Match.id == goal.match_id))
        match = match_result.scalar_one_or_none()

        if match:
            # Reverse the score change
            own_goal = goal.goal_type == GoalType.OWN_GOAL
            if own_goal:
                if goal.team_id == match.team_home_id:
                    match.score_away = max(0, match.score_away - 1)
                else:
                    match.score_home = max(0, match.score_home - 1)
            else:
                if goal.team_id == match.team_home_id:
                    match.score_home = max(0, match.score_home - 1)
                else:
                    match.score_away = max(0, match.score_away - 1)

        await session.delete(goal)
        await session.commit()

        return web.json_response({
            "ok": True,
            "score_home": match.score_home if match else 0,
            "score_away": match.score_away if match else 0,
        })


async def api_referee_sub(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/sub — замена игрока"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    team_id = int(body["team_id"])
    player_out_id = int(body["player_out_id"])
    player_in_id = int(body["player_in_id"])

    async with AsyncSessionFactory() as session:
        # Remove player_out from team
        out_result = await session.execute(
            select(TeamPlayer).where(
                TeamPlayer.team_id == team_id,
                TeamPlayer.player_id == player_out_id,
            )
        )
        tp_out = out_result.scalar_one_or_none()
        if tp_out:
            await session.delete(tp_out)

        # Add player_in to team (only if not already there)
        in_result = await session.execute(
            select(TeamPlayer).where(
                TeamPlayer.team_id == team_id,
                TeamPlayer.player_id == player_in_id,
            )
        )
        tp_in_existing = in_result.scalar_one_or_none()
        if not tp_in_existing:
            session.add(TeamPlayer(team_id=team_id, player_id=player_in_id))

        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_goalkeeper(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/goalkeeper — назначить вратаря"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    team_id = int(body["team_id"])
    player_id = int(body["player_id"])

    async with AsyncSessionFactory() as session:
        existing_result = await session.execute(
            select(MatchGoalkeeper).where(
                MatchGoalkeeper.match_id == match_id,
                MatchGoalkeeper.team_id == team_id,
            )
        )
        gk = existing_result.scalar_one_or_none()
        if gk:
            gk.player_id = player_id
            gk.saves = 0
        else:
            session.add(MatchGoalkeeper(
                match_id=match_id,
                team_id=team_id,
                player_id=player_id,
                saves=0,
            ))
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_save(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/save — отметить сейв"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    team_id = int(body["team_id"])

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(MatchGoalkeeper).where(
                MatchGoalkeeper.match_id == match_id,
                MatchGoalkeeper.team_id == team_id,
            )
        )
        gk = result.scalar_one_or_none()
        if not gk:
            raise web.HTTPNotFound(reason="Goalkeeper not assigned for this team")

        gk.saves += 1
        await session.commit()
        saves = gk.saves

    return web.json_response({"ok": True, "saves": saves})


async def api_referee_gameday_finish(request: web.Request) -> web.Response:
    """POST /api/referee/gameday/{game_day_id}/finish — завершить игровой день"""
    game_day_id = int(request.match_info["game_day_id"])

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(GameDay).where(GameDay.id == game_day_id)
        )
        game_day = result.scalar_one_or_none()
        if not game_day:
            raise web.HTTPNotFound(reason="GameDay not found")

        game_day.status = GameDayStatus.FINISHED
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_penalty_start(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/penalty/start"""
    match_id = int(request.match_info["match_id"])

    async with AsyncSessionFactory() as session:
        # Check if already exists
        ps_res = await session.execute(
            select(PenaltyShootout).where(PenaltyShootout.match_id == match_id)
        )
        ps = ps_res.scalar_one_or_none()
        if ps:
            return web.json_response({"ok": True})

        match_res = await session.execute(select(Match).where(Match.id == match_id))
        match = match_res.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        ps = PenaltyShootout(
            match_id=match_id,
            first_team_id=match.team_home_id,
            score_home=0,
            score_away=0,
            kick_number=1,
            current_side=0,
            finished=False,
        )
        session.add(ps)
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_penalty_kick(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/penalty/kick"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    side = body.get("side")  # "home" or "away"
    scored = bool(body.get("scored", False))

    async with AsyncSessionFactory() as session:
        ps_res = await session.execute(
            select(PenaltyShootout).where(PenaltyShootout.match_id == match_id)
        )
        ps = ps_res.scalar_one_or_none()
        if not ps:
            raise web.HTTPNotFound(reason="Penalty shootout not found")

        if side == "home" and scored:
            ps.score_home += 1
        elif side == "away" and scored:
            ps.score_away += 1

        await session.commit()

    return web.json_response({"ok": True, "score_home": ps.score_home, "score_away": ps.score_away})


async def api_referee_penalty_finish(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/penalty/finish"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    winner = body.get("winner")  # "home" or "away"

    async with AsyncSessionFactory() as session:
        ps_res = await session.execute(
            select(PenaltyShootout).where(PenaltyShootout.match_id == match_id)
        )
        ps = ps_res.scalar_one_or_none()
        if not ps:
            raise web.HTTPNotFound(reason="Penalty shootout not found")

        match_res = await session.execute(select(Match).where(Match.id == match_id))
        match = match_res.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        ps.finished = True
        ps.winner_team_id = match.team_home_id if winner == "home" else match.team_away_id
        await session.commit()

    return web.json_response({"ok": True})


async def api_referee_extend(request: web.Request) -> web.Response:
    """POST /api/referee/match/{match_id}/extend"""
    match_id = int(request.match_info["match_id"])
    body = await request.json()
    seconds = int(body.get("seconds", 30))

    async with AsyncSessionFactory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match:
            raise web.HTTPNotFound(reason="Match not found")

        current = match.duration_min or 0
        match.duration_min = round(current + seconds / 60, 1)
        await session.commit()
        new_duration = match.duration_min

    return web.json_response({"ok": True, "duration_min": new_duration})


async def api_referee_gameday_rosters(request: web.Request) -> web.Response:
    """GET /api/referee/gameday/{game_day_id}/rosters"""
    game_day_id = int(request.match_info["game_day_id"])

    async with AsyncSessionFactory() as session:
        teams_res = await session.execute(
            select(Team)
            .options(
                selectinload(Team.players).selectinload(TeamPlayer.player)
            )
            .where(Team.game_day_id == game_day_id)
            .order_by(Team.id)
        )
        teams = teams_res.scalars().all()

        teams_data = []
        for t in teams:
            players = [
                {"id": tp.player.id, "name": tp.player.name}
                for tp in (t.players or [])
                if tp.player
            ]
            teams_data.append({
                "id": t.id,
                "name": t.name,
                "emoji": t.color_emoji or "⚽",
                "players": players,
            })

    return web.json_response({"teams": teams_data})


async def api_referee_new_match(request: web.Request) -> web.Response:
    """POST /api/referee/gameday/{game_day_id}/new_match — создать новый матч"""
    game_day_id = int(request.match_info["game_day_id"])
    body = await request.json()
    team_home_id = int(body["team_home_id"])
    team_away_id = int(body["team_away_id"])
    stage = body.get("stage", "group")

    async with AsyncSessionFactory() as session:
        game_day = await session.get(GameDay, game_day_id)
        if not game_day:
            raise web.HTTPNotFound(reason="GameDay not found")

        # Определяем следующий match_order
        order_res = await session.execute(
            select(Match.match_order)
            .where(Match.game_day_id == game_day_id)
            .order_by(Match.match_order.desc())
            .limit(1)
        )
        last_order = order_res.scalar() or 0

        match = Match(
            game_day_id=game_day_id,
            team_home_id=team_home_id,
            team_away_id=team_away_id,
            match_stage=stage,
            match_format=game_day.match_format,
            duration_min=game_day.match_duration_min,
            goals_to_win=game_day.goals_to_win,
            status=MatchStatus.SCHEDULED,
            match_order=last_order + 1,
        )
        session.add(match)
        await session.commit()

    return web.json_response({"ok": True})


def create_webapp() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/standings", api_standings)
    # Referee routes
    app.router.add_get("/referee", referee_page)
    app.router.add_get("/api/referee/gameday/{game_day_id}", api_referee_gameday)
    app.router.add_get("/api/referee/match/{match_id}", api_referee_match)
    app.router.add_post("/api/referee/match/{match_id}/start", api_referee_start)
    app.router.add_post("/api/referee/match/{match_id}/finish", api_referee_finish)
    app.router.add_post("/api/referee/match/{match_id}/goal", api_referee_goal)
    app.router.add_post("/api/referee/match/{match_id}/card", api_referee_card)
    app.router.add_post("/api/referee/match/{match_id}/sub", api_referee_sub)
    app.router.add_post("/api/referee/match/{match_id}/goalkeeper", api_referee_goalkeeper)
    app.router.add_post("/api/referee/match/{match_id}/save", api_referee_save)
    app.router.add_delete("/api/referee/goal/{goal_id}", api_referee_delete_goal)
    app.router.add_post("/api/referee/gameday/{game_day_id}/finish", api_referee_gameday_finish)
    app.router.add_post("/api/referee/gameday/{game_day_id}/new_match", api_referee_new_match)
    # New routes
    app.router.add_post("/api/referee/match/{match_id}/penalty/start", api_referee_penalty_start)
    app.router.add_post("/api/referee/match/{match_id}/penalty/kick", api_referee_penalty_kick)
    app.router.add_post("/api/referee/match/{match_id}/penalty/finish", api_referee_penalty_finish)
    app.router.add_post("/api/referee/match/{match_id}/extend", api_referee_extend)
    app.router.add_get("/api/referee/gameday/{game_day_id}/rosters", api_referee_gameday_rosters)
    return app
