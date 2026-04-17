"""
Bilingual texts for Football Tournament Bot.
Supported languages: ru (Russian), en (English).
"""


def t(key: str, lang: str = "ru", **kwargs) -> str:
    """Get translated text by key and language."""
    text = TEXTS.get(lang, TEXTS["ru"]).get(key) or TEXTS["ru"].get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def goals_word(count: int, lang: str = "ru") -> str:
    """Return correct plural form of 'goal' / 'гол'."""
    if lang == "en":
        return "goal" if count == 1 else "goals"
    # Russian pluralization
    if count % 100 in range(11, 20):
        return "голов"
    r = count % 10
    if r == 1:
        return "гол"
    if r in (2, 3, 4):
        return "гола"
    return "голов"


TEXTS = {
    "ru": {
        # ── Registration ──────────────────────────────────────────────────
        "reg_welcome": (
            "👋 Привет! Добро пожаловать в <b>Football Manager Bot</b>!\n\n"
            "Ты ещё не зарегистрирован. Давай исправим это!\n\n"
            "Нажми /register чтобы создать профиль игрока."
        ),
        "reg_start": (
            "👤 <b>Регистрация</b>\n\n"
            "Шаг 1 из 3\n\n"
            "Как тебя зовут?\n"
            "<i>Введи имя и фамилию, например: Иван Петров</i>"
        ),
        "reg_name_too_short": "❌ Имя слишком короткое. Введи минимум 2 символа:",
        "reg_choose_position": (
            "✅ Имя: <b>{name}</b>\n\n"
            "Шаг 2 из 3\n\n"
            "Выбери свою позицию:"
        ),
        "reg_choose_rating": (
            "✅ Позиция: <b>{position}</b>\n\n"
            "Шаг 3 из 3\n\n"
            "Оцени свой уровень игры от 1 до 10:\n"
            "<i>1 — новичок, 10 — профессионал</i>"
        ),
        "reg_invalid_rating": "❌ Введи число от 1 до 10:",
        "reg_complete": (
            "🎉 <b>Регистрация завершена!</b>\n\n"
            "👤 Имя: <b>{name}</b>\n"
            "{position}\n"
            "⭐ Начальный рейтинг: <b>{rating}</b>\n\n"
            "Добро пожаловать в лигу! ⚽"
        ),
        "reg_already": "✅ Ты уже зарегистрирован! Используй /start для главного меню.",
        "choose_language": "🌐 <b>Выбери язык / Choose language:</b>",
        "lang_set_ru": "✅ Язык изменён на Русский 🇷🇺",
        "lang_set_en": "✅ Language changed to English 🇬🇧",

        # ── Main menu ────────────────────────────────────────────────────
        "main_menu_greeting": (
            "⚽ Привет, <b>{name}</b>!\n\n"
            "📍 Позиция: {position}\n"
            "⭐ Рейтинг: {rating}{provisional}\n"
            "💰 Баланс: {balance} сум.\n\n"
            "Выбери действие:"
        ),
        "provisional_label": " <i>(провизорный)</i>",
        "no_league_hint": "\n\n💡 <i>У тебя нет лиги. /create_league — создай свою!</i>",

        # ── Profile ───────────────────────────────────────────────────────
        "profile_title": (
            "👤 <b>Профиль игрока</b>\n\n"
            "Имя: <b>{name}</b>\n"
            "Позиция: {position}\n"
            "⭐ Рейтинг: <b>{rating}</b>{provisional}\n"
            "✅ Посещаемость: <b>{reliability}%</b>\n"
            "⚽ Игр: <b>{games}</b>\n"
            "💰 Баланс: <b>{balance} руб.</b>"
        ),

        # ── Standings / stats ─────────────────────────────────────────────
        "standings_empty": "🏆 <b>Таблица турнира</b>\n\nДанных пока нет.",
        "standings_title": "🏆 <b>Таблица турнира</b> — {date}",
        "standings_no_matches": "Матчей ещё не сыграно.",
        "standings_recent": "\n<b>Последние результаты:</b>",
        "standings_upcoming": "\n<b>Предстоящие матчи:</b>",
        "my_stats_title": (
            "📊 <b>Статистика — {name}</b>\n\n"
            "⚽ Игр сыграно: <b>{games}</b>\n"
            "🥅 Голов: <b>{goals}</b>\n"
            "✅ Надёжность: <b>{reliability}%</b>\n"
            "⭐ Рейтинг: <b>{rating}</b>\n"
        ),
        "results_empty": "📋 Сыгранных матчей пока нет.",
        "results_title": "📋 <b>Результаты игр</b>\n",
        "no_players": "👥 Игроков пока нет.",
        "players_title": "👥 <b>Все игроки</b>\n",

        # ── Attendance ────────────────────────────────────────────────────
        "join_success": (
            "✅ <b>Ты записан на игру!</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "Бот напомнит за 2 часа до начала."
        ),
        "join_waitlist": (
            "⏳ Мест нет — ты в листе ожидания <b>#{position}</b>.\n\n"
            "Как только кто-то откажется — получишь уведомление."
        ),
        "join_declined": "❌ Ты отказался от участия.\n\nЕсли передумаешь — запишись снова.",
        "confirm_reminder": (
            "⏰ <b>Напоминание!</b>\n\n"
            "Игра через 2 часа!\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "Подтверди участие:"
        ),
        "confirm_yes_response": "✅ Отлично! Ждём тебя на игре 💪",
        "confirm_no_response": "😔 Жаль! Твоё место передано следующему игроку.",
        "confirm_late_response": "⏰ Понял, опаздываешь. Постарайся успеть!",
        "waitlist_promoted": (
            "🎉 <b>Место освободилось!</b>\n\n"
            "Ты переведён из листа ожидания в основной состав!\n\n"
            "📅 {date}\n"
            "📍 {location}"
        ),

        # ── Match result broadcast ────────────────────────────────────────
        "match_result_text": (
            "🏁 <b>Финальный счёт</b>\n\n"
            "⚽ <b>{home}  {score_home} : {score_away}  {away}</b>\n"
        ),
        "match_cards_header": "\n\n<b>Карточки:</b>",

        # ── Finance broadcast ──────────────────────────────────────────────
        "finance_notice": (
            "💰 <b>Взнос за {game_name}</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "💵 Сумма к оплате: <b>{amount} сум.</b>\n\n"
            "Пожалуйста, оплати взнос организатору. Спасибо! 🙏"
        ),

        # ── Team assignment ───────────────────────────────────────────────
        "team_assigned": (
            "⚽ <b>Команды на игру {game_name} сформированы!</b>\n\n"
            "Мы провели разбивку на команды с балансировкой по рейтингу и позициям.\n\n"
            "Ты сегодня играешь в команде <b>{team_color} {team_name}</b>.\n\n"
            "С тобой в команде играют: <b>{teammates}</b>\n\n"
            "Удачи на игре! 🏆"
        ),

        # ── Tournament results ────────────────────────────────────────────
        "tournament_results_header": "🏆 <b>Итоги турнира — {game_name}</b>\n",
        "place_1": "🥇 1-е место",
        "place_2": "🥈 2-е место",
        "place_3": "🥉 3-е место",
        "place_4": "❤️ Приз зрительских симпатий (4-е место)",
        "top_scorer": "\n⚽ <b>Лучший бомбардир:</b> {name} ({count} {goals_word})",
        "best_player": "⭐ <b>Лучший игрок:</b> {name}",
        "tournament_thanks": "\n🙏 Всем спасибо за игру! До встречи на следующем турнире!",

        # ── Rating voting ─────────────────────────────────────────────────
        "rating_invite": (
            "⭐ <b>Рейтинг-голосование!</b>\n\n"
            "Оцени других игроков лиги от 1 до 10.\n"
            "Твои оценки влияют на рейтинг участников.\n\n"
            "<i>Займёт 1-2 минуты</i>"
        ),
        "rating_invite_gameday": (
            "⭐ <b>Оцени игроков!</b>\n\n"
            "Перед делением на команды ({game_name}) оцени участников от 1 до 10.\n\n"
            "Это займёт 1–2 минуты и поможет сделать команды сбалансированнее."
        ),
        "rating_voted": (
            "✅ <b>Голоса отправлены!</b>\n\n"
            "Ты оценил {count} игроков.\n"
            "Спасибо! Результаты будут применены после завершения раунда. 🙏"
        ),
        "rating_vote_nominee": (
            "⭐ <b>Голосование</b> — {current}/{total}\n\n"
            "👤 <b>{name}</b>\n\n"
            "Твоя оценка: <b>{score}</b>\n\n"
            "<i>Оцени от 1 (слабо) до 10 (отлично)</i>"
        ),
        "score_not_set": "<i>не выбрана</i>",

        # ── Buttons ───────────────────────────────────────────────────────
        "btn_upcoming_game": "📅 Ближайшая игра",
        "btn_standings": "🏆 Таблица турнира",
        "btn_my_stats": "📊 Моя статистика",
        "btn_players_list": "👥 Игроки",
        "btn_results": "📋 Результаты игр",
        "btn_rules": "📜 Регламент",
        "btn_language": "🌐 Язык / Language",
        "btn_profile": "👤 Мой профиль",
        "btn_rate_players": "⭐ Оценить игроков",
        "btn_back": "🔙 Назад",
        "btn_confirm_yes": "✅ Да, иду!",
        "btn_confirm_no": "❌ Не смогу",
        "btn_confirm_late": "⏰ Опаздываю",
        "btn_register": "✅ Согласен, записаться",
        "btn_cancel_reg": "❌ Отмена",
        "btn_read_rules": "📜 Читать Регламент",
        "btn_join": "✅ Записаться",
        "btn_decline": "❌ Не пойду",
        "btn_rate_players_start": "⭐ Оценить игроков",
        "btn_vote_prev": "◀️ Назад",
        "btn_vote_next": "▶️ Далее",
        "btn_vote_submit": "✅ Отправить голоса",

        # ── Position labels ───────────────────────────────────────────────
        "pos_gk": "🧤 Вратарь",
        "pos_def": "🛡 Защитник",
        "pos_mid": "⚙️ Полузащитник",
        "pos_fwd": "⚡ Нападающий",
    },

    "en": {
        # ── Registration ──────────────────────────────────────────────────
        "reg_welcome": (
            "👋 Hi! Welcome to <b>Football Manager Bot</b>!\n\n"
            "You're not registered yet. Let's fix that!\n\n"
            "Tap /register to create your player profile."
        ),
        "reg_start": (
            "👤 <b>Registration</b>\n\n"
            "Step 1 of 3\n\n"
            "What's your name?\n"
            "<i>Enter first and last name, e.g. John Smith</i>"
        ),
        "reg_name_too_short": "❌ Name too short. Enter at least 2 characters:",
        "reg_choose_position": (
            "✅ Name: <b>{name}</b>\n\n"
            "Step 2 of 3\n\n"
            "Choose your position:"
        ),
        "reg_choose_rating": (
            "✅ Position: <b>{position}</b>\n\n"
            "Step 3 of 3\n\n"
            "Rate your skill level from 1 to 10:\n"
            "<i>1 — beginner, 10 — professional</i>"
        ),
        "reg_invalid_rating": "❌ Enter a number from 1 to 10:",
        "reg_complete": (
            "🎉 <b>Registration complete!</b>\n\n"
            "👤 Name: <b>{name}</b>\n"
            "{position}\n"
            "⭐ Starting rating: <b>{rating}</b>\n\n"
            "Welcome to the league! ⚽"
        ),
        "reg_already": "✅ You're already registered! Use /start for the main menu.",
        "choose_language": "🌐 <b>Выбери язык / Choose language:</b>",
        "lang_set_ru": "✅ Язык изменён на Русский 🇷🇺",
        "lang_set_en": "✅ Language changed to English 🇬🇧",

        # ── Main menu ────────────────────────────────────────────────────
        "main_menu_greeting": (
            "⚽ Hey, <b>{name}</b>!\n\n"
            "📍 Position: {position}\n"
            "⭐ Rating: {rating}{provisional}\n"
            "💰 Balance: {balance} sum\n\n"
            "Choose an action:"
        ),
        "provisional_label": " <i>(provisional)</i>",
        "no_league_hint": "\n\n💡 <i>You have no league. /create_league — create one!</i>",

        # ── Profile ───────────────────────────────────────────────────────
        "profile_title": (
            "👤 <b>Player Profile</b>\n\n"
            "Name: <b>{name}</b>\n"
            "Position: {position}\n"
            "⭐ Rating: <b>{rating}</b>{provisional}\n"
            "✅ Attendance: <b>{reliability}%</b>\n"
            "⚽ Games: <b>{games}</b>\n"
            "💰 Balance: <b>{balance}</b>"
        ),

        # ── Standings / stats ─────────────────────────────────────────────
        "standings_empty": "🏆 <b>Tournament Standings</b>\n\nNo data yet.",
        "standings_title": "🏆 <b>Tournament Standings</b> — {date}",
        "standings_no_matches": "No matches played yet.",
        "standings_recent": "\n<b>Recent results:</b>",
        "standings_upcoming": "\n<b>Upcoming matches:</b>",
        "my_stats_title": (
            "📊 <b>Stats — {name}</b>\n\n"
            "⚽ Games played: <b>{games}</b>\n"
            "🥅 Goals: <b>{goals}</b>\n"
            "✅ Reliability: <b>{reliability}%</b>\n"
            "⭐ Rating: <b>{rating}</b>\n"
        ),
        "results_empty": "📋 No finished matches yet.",
        "results_title": "📋 <b>Match Results</b>\n",
        "no_players": "👥 No players yet.",
        "players_title": "👥 <b>All Players</b>\n",

        # ── Attendance ────────────────────────────────────────────────────
        "join_success": (
            "✅ <b>You're registered for the game!</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "The bot will remind you 2 hours before."
        ),
        "join_waitlist": (
            "⏳ No spots available — you're on the waitlist <b>#{position}</b>.\n\n"
            "You'll be notified as soon as a spot opens up."
        ),
        "join_declined": "❌ You've declined.\n\nChange your mind? Register again.",
        "confirm_reminder": (
            "⏰ <b>Reminder!</b>\n\n"
            "Game in 2 hours!\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "Confirm your attendance:"
        ),
        "confirm_yes_response": "✅ Great! See you at the game 💪",
        "confirm_no_response": "😔 Too bad! Your spot has been passed to the next player.",
        "confirm_late_response": "⏰ Got it, you'll be late. Try to make it!",
        "waitlist_promoted": (
            "🎉 <b>A spot opened up!</b>\n\n"
            "You've been moved from the waitlist to the main roster!\n\n"
            "📅 {date}\n"
            "📍 {location}"
        ),

        # ── Match result broadcast ────────────────────────────────────────
        "match_result_text": (
            "🏁 <b>Final Score</b>\n\n"
            "⚽ <b>{home}  {score_home} : {score_away}  {away}</b>\n"
        ),
        "match_cards_header": "\n\n<b>Cards:</b>",

        # ── Finance broadcast ──────────────────────────────────────────────
        "finance_notice": (
            "💰 <b>Payment for {game_name}</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "💵 Amount due: <b>{amount} sum</b>\n\n"
            "Please pay the fee to the organizer. Thank you! 🙏"
        ),

        # ── Team assignment ───────────────────────────────────────────────
        "team_assigned": (
            "⚽ <b>Teams for {game_name} are set!</b>\n\n"
            "We balanced teams by rating and position.\n\n"
            "You're playing in team <b>{team_color} {team_name}</b> today.\n\n"
            "Your teammates: <b>{teammates}</b>\n\n"
            "Good luck! 🏆"
        ),

        # ── Tournament results ────────────────────────────────────────────
        "tournament_results_header": "🏆 <b>Tournament Results — {game_name}</b>\n",
        "place_1": "🥇 1st place",
        "place_2": "🥈 2nd place",
        "place_3": "🥉 3rd place",
        "place_4": "❤️ Fan Favourite Award (4th place)",
        "top_scorer": "\n⚽ <b>Top Scorer:</b> {name} ({count} {goals_word})",
        "best_player": "⭐ <b>Best Player:</b> {name}",
        "tournament_thanks": "\n🙏 Thanks everyone for playing! See you at the next tournament!",

        # ── Rating voting ─────────────────────────────────────────────────
        "rating_invite": (
            "⭐ <b>Rating Vote!</b>\n\n"
            "Rate other players from 1 to 10.\n"
            "Your scores affect player ratings.\n\n"
            "<i>Takes 1-2 minutes</i>"
        ),
        "rating_invite_gameday": (
            "⭐ <b>Rate the Players!</b>\n\n"
            "Before forming teams ({game_name}) rate participants from 1 to 10.\n\n"
            "Takes 1–2 minutes and helps balance the teams."
        ),
        "rating_voted": (
            "✅ <b>Votes submitted!</b>\n\n"
            "You rated {count} players.\n"
            "Thank you! Results will be applied when the round ends. 🙏"
        ),
        "rating_vote_nominee": (
            "⭐ <b>Voting</b> — {current}/{total}\n\n"
            "👤 <b>{name}</b>\n\n"
            "Your score: <b>{score}</b>\n\n"
            "<i>Rate 1 (weak) to 10 (excellent)</i>"
        ),
        "score_not_set": "<i>not set</i>",

        # ── Buttons ───────────────────────────────────────────────────────
        "btn_upcoming_game": "📅 Upcoming Game",
        "btn_standings": "🏆 Standings",
        "btn_my_stats": "📊 My Stats",
        "btn_players_list": "👥 Players",
        "btn_results": "📋 Match Results",
        "btn_rules": "📜 Rules",
        "btn_language": "🌐 Язык / Language",
        "btn_profile": "👤 My Profile",
        "btn_rate_players": "⭐ Rate Players",
        "btn_back": "🔙 Back",
        "btn_confirm_yes": "✅ Yes, I'm in!",
        "btn_confirm_no": "❌ Can't make it",
        "btn_confirm_late": "⏰ Running late",
        "btn_register": "✅ Agree & Register",
        "btn_cancel_reg": "❌ Cancel",
        "btn_read_rules": "📜 Read the Rules",
        "btn_join": "✅ Join",
        "btn_decline": "❌ Not going",
        "btn_rate_players_start": "⭐ Rate Players",
        "btn_vote_prev": "◀️ Prev",
        "btn_vote_next": "▶️ Next",
        "btn_vote_submit": "✅ Submit votes",

        # ── Position labels ───────────────────────────────────────────────
        "pos_gk": "🧤 Goalkeeper",
        "pos_def": "🛡 Defender",
        "pos_mid": "⚙️ Midfielder",
        "pos_fwd": "⚡ Forward",
    },
}
