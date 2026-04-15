"""
Telegram WebApp — живая таблица турнира.
aiohttp-сервер слушает на PORT (Railway).
  GET /          → HTML-страница с таблицей
  GET /api/standings  → JSON с данными турнира
"""
import json
import os
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.engine import AsyncSessionFactory
from app.database.models import (
    GameDay, GameDayStatus, Match, MatchStatus, Team,
    Goal, GoalType, Attendance, AttendanceResponse, Player,
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


def create_webapp() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/standings", api_standings)
    return app
