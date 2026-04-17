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


def t_g(key: str, lang: str = "ru", gender: str = "m", **kwargs) -> str:
    """Get text with gender awareness. Uses {key}_f for Russian feminine forms."""
    if lang == "ru" and gender == "f":
        feminine_key = f"{key}_f"
        text = TEXTS.get(lang, {}).get(feminine_key)
        if text:
            return text.format(**kwargs) if kwargs else text
    return t(key, lang, **kwargs)


def goals_word(count: int, lang: str = "ru") -> str:
    """Return correct plural form of 'goal' / 'гол' / 'gol'."""
    if lang == "en":
        return "goal" if count == 1 else "goals"
    if lang == "uz":
        return "gol"  # Uzbek has no grammatical plural distinction here
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
        "choose_gender": (
            "👤 <b>Как к тебе обращаться?</b>\n\n"
            "Это нужно чтобы бот обращался к тебе правильно."
        ),
        "gender_set": "✅ Готово! Обращение сохранено.",
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
        "join_success_f": (
            "✅ <b>Ты записана на игру!</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "Бот напомнит за 2 часа до начала."
        ),
        "join_waitlist": (
            "⏳ Мест нет — ты в листе ожидания <b>#{position}</b>.\n\n"
            "Как только кто-то откажется — получишь уведомление."
        ),
        "join_declined": "❌ Ты отказался от участия.\n\nЕсли передумаешь — запишись снова.",
        "join_declined_f": "❌ Ты отказалась от участия.\n\nЕсли передумаешь — запишись снова.",
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
        "waitlist_promoted_f": (
            "🎉 <b>Место освободилось!</b>\n\n"
            "Ты переведена из листа ожидания в основной состав!\n\n"
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

        # ── My Team (I-040) ───────────────────────────────────────────────
        "myteam_no_game": "📅 Нет активных турниров.",
        "myteam_no_teams": "⚽ Команды для <b>{game_name}</b> ещё не сформированы.\n\nОрганизатор разобьёт команды ближе к игре.",
        "myteam_not_in_team": "🤔 Тебя нет ни в одной команде на ближайший турнир.\n\nВозможно, ты не записан или команды ещё не распределены.",
        "myteam_title": (
            "👥 <b>Твоя команда — {game_name}</b>\n"
            "📅 {date} | 📍 {location}\n\n"
            "{team_emoji} <b>{team_name}</b>\n\n"
            "<b>Состав:</b>\n"
        ),

        # ── Top Scorers (I-020) ───────────────────────────────────────────
        "top_scorers_title": "⚽ <b>Бомбардиры</b>\n",
        "top_scorers_empty": "📊 Голов ещё не забито.",
        "top_scorers_all_time": "📊 <b>Лучшие бомбардиры — все турниры</b>\n",

        # ── My stats updated (I-019) ───────────────────────────────────────
        "my_stats_title": (
            "📊 <b>Моя статистика — {name}</b>\n\n"
            "⚽ Игр сыграно: <b>{games}</b>\n"
            "🥅 Голов: <b>{goals}</b>\n"
            "🟨 Жёлтых карточек: <b>{yellow_cards}</b>\n"
            "🟥 Красных карточек: <b>{red_cards}</b>\n"
            "✅ Надёжность: <b>{reliability}%</b>\n"
            "⭐ Рейтинг: <b>{rating}</b>"
        ),

        # ── Match Schedule (I-042) ─────────────────────────────────────────
        "schedule_title": "📅 <b>Расписание матчей — {game_name}</b>\n",
        "schedule_empty": "📋 Расписание ещё не создано.\n\nДобавь матчи по кнопке ниже.",
        "schedule_match_row": "{num}. {emoji1} {team1} vs {emoji2} {team2}",
        "schedule_add_title": "📅 <b>Добавить матч в расписание</b>\n\nШаг 1: выбери <b>Команду 1</b>:",
        "schedule_pick_team2": "✅ Команда 1: <b>{team1}</b>\n\nШаг 2: выбери <b>Команду 2</b>:",
        "schedule_added": "✅ Матч добавлен в расписание под номером <b>#{num}</b>.",
        "schedule_started": "▶️ Матч <b>{num}</b> начат!",
        "schedule_all_done": "🏁 Все матчи из расписания сыграны!",

        # ── Post Results (I-013) ───────────────────────────────────────────
        "results_broadcast_header": (
            "🏁 <b>Итоги {game_name}</b>\n\n"
        ),
        "results_broadcast_sent": "✅ Итоги турнира разосланы <b>{count}</b> игрокам.",
        "results_broadcast_empty": "⚠️ Нет завершённых матчей для рассылки.",

        # ── Channel Post (I-043) ───────────────────────────────────────────
        "channel_posted": "✅ Итоги опубликованы в канале.",
        "channel_not_set": (
            "⚠️ Канал не настроен.\n\n"
            "Добавь переменную CHANNEL_ID в настройки Railway\n"
            "<i>(например: @mychannel или -1001234567890)</i>"
        ),

        # ── Buttons ───────────────────────────────────────────────────────
        "btn_my_team": "👥 Моя команда",
        "btn_top_scorers": "⚽ Бомбардиры",
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

        # ── My Team / Stats (EN) ─────────────────────────────────────────
        "myteam_no_game": "📅 No active tournaments.",
        "myteam_no_teams": "⚽ Teams for <b>{game_name}</b> haven't been set yet.",
        "myteam_not_in_team": "🤔 You're not in any team for the nearest tournament.",
        "myteam_title": (
            "👥 <b>Your Team — {game_name}</b>\n"
            "📅 {date} | 📍 {location}\n\n"
            "{team_emoji} <b>{team_name}</b>\n\n"
            "<b>Roster:</b>\n"
        ),
        "top_scorers_title": "⚽ <b>Top Scorers</b>\n",
        "top_scorers_empty": "📊 No goals scored yet.",
        "top_scorers_all_time": "📊 <b>All-Time Top Scorers</b>\n",
        "my_stats_title": (
            "📊 <b>My Stats — {name}</b>\n\n"
            "⚽ Games played: <b>{games}</b>\n"
            "🥅 Goals: <b>{goals}</b>\n"
            "🟨 Yellow cards: <b>{yellow_cards}</b>\n"
            "🟥 Red cards: <b>{red_cards}</b>\n"
            "✅ Reliability: <b>{reliability}%</b>\n"
            "⭐ Rating: <b>{rating}</b>"
        ),
        "results_broadcast_sent": "✅ Results sent to <b>{count}</b> players.",
        "results_broadcast_empty": "⚠️ No finished matches to broadcast.",
        "channel_posted": "✅ Results published to channel.",
        "channel_not_set": "⚠️ Channel not configured. Set CHANNEL_ID in Railway settings.",

        # ── Buttons ───────────────────────────────────────────────────────
        "btn_my_team": "👥 My Team",
        "btn_top_scorers": "⚽ Scorers",
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

    "uz": {
        # ── Registration ──────────────────────────────────────────────────
        "reg_welcome": (
            "👋 Salom! <b>Football Manager Bot</b>ga xush kelibsiz!\n\n"
            "Siz hali ro'yxatdan o'tmagansiz. Keling, buni tuzatamiz!\n\n"
            "Profil yaratish uchun /register ni bosing."
        ),
        "reg_start": (
            "👤 <b>Ro'yxatdan o'tish</b>\n\n"
            "1-qadam / 3\n\n"
            "Ismingiz nima?\n"
            "<i>Ism va familiyangizni kiriting, masalan: Jasur Karimov</i>"
        ),
        "reg_name_too_short": "❌ Ism juda qisqa. Kamida 2 ta belgi kiriting:",
        "reg_choose_position": (
            "✅ Ism: <b>{name}</b>\n\n"
            "2-qadam / 3\n\n"
            "O'z pozitsiyangizni tanlang:"
        ),
        "reg_choose_rating": (
            "✅ Pozitsiya: <b>{position}</b>\n\n"
            "3-qadam / 3\n\n"
            "O'z darajangizni 1 dan 10 gacha baholang:\n"
            "<i>1 — yangi boshlovchi, 10 — professional</i>"
        ),
        "reg_invalid_rating": "❌ 1 dan 10 gacha son kiriting:",
        "reg_complete": (
            "🎉 <b>Ro'yxatdan o'tish yakunlandi!</b>\n\n"
            "👤 Ism: <b>{name}</b>\n"
            "{position}\n"
            "⭐ Boshlang'ich reyting: <b>{rating}</b>\n\n"
            "Ligaga xush kelibsiz! ⚽"
        ),
        "reg_already": "✅ Siz allaqachon ro'yxatdan o'tgansiz! Asosiy menyu uchun /start ni bosing.",
        "choose_gender": (
            "👤 <b>Sizga qanday murojaat qilaylik?</b>\n\n"
            "Bu bot sizga to'g'ri murojaat qilishi uchun kerak."
        ),
        "gender_set": "✅ Tayyor! Murojaat shakli saqlandi.",
        "choose_language": "🌐 <b>Выбери язык / Choose language / Til tanlang:</b>",
        "lang_set_ru": "✅ Язык изменён на Русский 🇷🇺",
        "lang_set_en": "✅ Language changed to English 🇬🇧",
        "lang_set_uz": "✅ Til o'zbek tiliga o'zgartirildi 🇺🇿",

        # ── Main menu ────────────────────────────────────────────────────
        "main_menu_greeting": (
            "⚽ Salom, <b>{name}</b>!\n\n"
            "📍 Pozitsiya: {position}\n"
            "⭐ Reyting: {rating}{provisional}\n"
            "💰 Balans: {balance} so'm.\n\n"
            "Amalni tanlang:"
        ),
        "provisional_label": " <i>(vaqtinchalik)</i>",
        "no_league_hint": "\n\n💡 <i>Sizda liga yo'q. /create_league — o'z ligangizni yarating!</i>",

        # ── Profile ───────────────────────────────────────────────────────
        "profile_title": (
            "👤 <b>O'yinchi profili</b>\n\n"
            "Ism: <b>{name}</b>\n"
            "Pozitsiya: {position}\n"
            "⭐ Reyting: <b>{rating}</b>{provisional}\n"
            "✅ Ishonchlilik: <b>{reliability}%</b>\n"
            "⚽ O'yinlar: <b>{games}</b>\n"
            "💰 Balans: <b>{balance} so'm</b>"
        ),

        # ── Standings / stats ─────────────────────────────────────────────
        "standings_empty": "🏆 <b>Turnir jadvali</b>\n\nHali ma'lumot yo'q.",
        "standings_title": "🏆 <b>Turnir jadvali</b> — {date}",
        "standings_no_matches": "Hali o'yin o'ynalmagan.",
        "standings_recent": "\n<b>So'nggi natijalar:</b>",
        "standings_upcoming": "\n<b>Kelgusi o'yinlar:</b>",
        "my_stats_title": (
            "📊 <b>Mening statistikam — {name}</b>\n\n"
            "⚽ O'ynalgan o'yinlar: <b>{games}</b>\n"
            "🥅 Gollar: <b>{goals}</b>\n"
            "🟨 Sariq kartochkalar: <b>{yellow_cards}</b>\n"
            "🟥 Qizil kartochkalar: <b>{red_cards}</b>\n"
            "✅ Ishonchlilik: <b>{reliability}%</b>\n"
            "⭐ Reyting: <b>{rating}</b>"
        ),
        "results_empty": "📋 Hali yakunlangan o'yinlar yo'q.",
        "results_title": "📋 <b>O'yin natijalari</b>\n",
        "no_players": "👥 Hali o'yinchilar yo'q.",
        "players_title": "👥 <b>Barcha o'yinchilar</b>\n",

        # ── Attendance ────────────────────────────────────────────────────
        "join_success": (
            "✅ <b>Siz o'yinga yozildingiz!</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "Bot boshlanishdan 2 soat oldin eslatib qo'yadi."
        ),
        "join_waitlist": (
            "⏳ Joy yo'q — siz kutish ro'yxatidasiz <b>#{position}</b>.\n\n"
            "Biror kishi voz kechganda, siz xabardor bo'lasiz."
        ),
        "join_declined": "❌ Siz ishtirokdan voz kechdingiz.\n\nFikringiz o'zgardimi? Qayta yozilib oling.",
        "confirm_reminder": (
            "⏰ <b>Eslatma!</b>\n\n"
            "O'yin 2 soatdan keyin!\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "Qatnashishingizni tasdiqlang:"
        ),
        "confirm_yes_response": "✅ Ajoyib! O'yinda ko'rishguncha 💪",
        "confirm_no_response": "😔 Afsuski! Sizning joyingiz keyingi o'yinchiga berildi.",
        "confirm_late_response": "⏰ Tushundim, kechikasiz. Ulgurishga harakat qiling!",
        "waitlist_promoted": (
            "🎉 <b>Joy bo'shadi!</b>\n\n"
            "Siz kutish ro'yxatidan asosiy tarkibga o'tkazildingiz!\n\n"
            "📅 {date}\n"
            "📍 {location}"
        ),

        # ── Match result broadcast ────────────────────────────────────────
        "match_result_text": (
            "🏁 <b>Yakuniy hisob</b>\n\n"
            "⚽ <b>{home}  {score_home} : {score_away}  {away}</b>\n"
        ),
        "match_cards_header": "\n\n<b>Kartochkalar:</b>",

        # ── Finance broadcast ──────────────────────────────────────────────
        "finance_notice": (
            "💰 <b>{game_name} uchun to'lov</b>\n\n"
            "📅 {date}\n"
            "📍 {location}\n\n"
            "💵 To'lov miqdori: <b>{amount} so'm</b>\n\n"
            "Iltimos, to'lovni tashkilotchiga amalga oshiring. Rahmat! 🙏"
        ),

        # ── Team assignment ───────────────────────────────────────────────
        "team_assigned": (
            "⚽ <b>{game_name} uchun jamoalar tuzildi!</b>\n\n"
            "Jamoalar reyting va pozitsiyalar bo'yicha teng taqsimlandi.\n\n"
            "Siz bugun <b>{team_color} {team_name}</b> jamoasida o'ynaysiz.\n\n"
            "Jamoangiz: <b>{teammates}</b>\n\n"
            "Omad! 🏆"
        ),

        # ── Tournament results ────────────────────────────────────────────
        "tournament_results_header": "🏆 <b>Turnir yakunlari — {game_name}</b>\n",
        "place_1": "🥇 1-o'rin",
        "place_2": "🥈 2-o'rin",
        "place_3": "🥉 3-o'rin",
        "place_4": "❤️ Tomoshabinlar sevimli (4-o'rin)",
        "top_scorer": "\n⚽ <b>Eng ko'p gol urgan:</b> {name} ({count} {goals_word})",
        "best_player": "⭐ <b>Eng yaxshi o'yinchi:</b> {name}",
        "tournament_thanks": "\n🙏 O'ynaganlarga rahmat! Keyingi turnirda ko'rishguncha!",

        # ── Rating voting ─────────────────────────────────────────────────
        "rating_invite": (
            "⭐ <b>Reyting ovoz berish!</b>\n\n"
            "Boshqa o'yinchilarni 1 dan 10 gacha baholang.\n"
            "Sizning baholaringiz ishtirokchilar reytingiga ta'sir qiladi.\n\n"
            "<i>1-2 daqiqa vaqt oladi</i>"
        ),
        "rating_invite_gameday": (
            "⭐ <b>O'yinchilarni baholang!</b>\n\n"
            "Jamoalarga bo'linishdan oldin ({game_name}) ishtirokchilarni 1 dan 10 gacha baholang.\n\n"
            "Bu 1–2 daqiqa vaqt oladi va jamoalarni tenglashtirish uchun yordam beradi."
        ),
        "rating_voted": (
            "✅ <b>Ovozlar yuborildi!</b>\n\n"
            "Siz {count} ta o'yinchini baholadingiz.\n"
            "Rahmat! Natijalar raund tugagandan keyin qo'llaniladi. 🙏"
        ),
        "rating_vote_nominee": (
            "⭐ <b>Ovoz berish</b> — {current}/{total}\n\n"
            "👤 <b>{name}</b>\n\n"
            "Sizning bahongiz: <b>{score}</b>\n\n"
            "<i>1 (zaif) dan 10 (a'lo) gacha baholang</i>"
        ),
        "score_not_set": "<i>tanlanmagan</i>",

        # ── My Team (I-040) ───────────────────────────────────────────────
        "myteam_no_game": "📅 Faol turnirlar yo'q.",
        "myteam_no_teams": "⚽ <b>{game_name}</b> uchun jamoalar hali tuzilmagan.\n\nTashkilotchi o'yin oldidan jamoalarni taqsimlab beradi.",
        "myteam_not_in_team": "🤔 Siz yaqin turnir uchun hech qaysi jamoada yo'qsiz.\n\nEhtimol, yozilmagansiz yoki jamoalar hali taqsimlanmagan.",
        "myteam_title": (
            "👥 <b>Sizning jamoangiz — {game_name}</b>\n"
            "📅 {date} | 📍 {location}\n\n"
            "{team_emoji} <b>{team_name}</b>\n\n"
            "<b>Tarkib:</b>\n"
        ),

        # ── Top Scorers (I-020) ───────────────────────────────────────────
        "top_scorers_title": "⚽ <b>Bombardirlar</b>\n",
        "top_scorers_empty": "📊 Hali gol urilmagan.",
        "top_scorers_all_time": "📊 <b>Eng yaxshi bombardirlar — barcha turnirlar</b>\n",

        # ── Match Schedule (I-042) ─────────────────────────────────────────
        "schedule_title": "📅 <b>O'yinlar jadvali — {game_name}</b>\n",
        "schedule_empty": "📋 Jadval hali tuzilmagan.\n\nQuyidagi tugma orqali o'yinlar qo'shing.",
        "schedule_match_row": "{num}. {emoji1} {team1} vs {emoji2} {team2}",
        "schedule_add_title": "📅 <b>Jadvalga o'yin qo'shish</b>\n\n1-qadam: <b>1-jamoani</b> tanlang:",
        "schedule_pick_team2": "✅ 1-jamoa: <b>{team1}</b>\n\n2-qadam: <b>2-jamoani</b> tanlang:",
        "schedule_added": "✅ O'yin jadvalga <b>#{num}</b> raqami ostida qo'shildi.",
        "schedule_started": "▶️ <b>{num}</b>-o'yin boshlandi!",
        "schedule_all_done": "🏁 Jadvaldan barcha o'yinlar o'ynaldi!",

        # ── Post Results (I-013) ───────────────────────────────────────────
        "results_broadcast_header": "🏁 <b>{game_name} yakunlari</b>\n\n",
        "results_broadcast_sent": "✅ Turnir yakunlari <b>{count}</b> ta o'yinchiga yuborildi.",
        "results_broadcast_empty": "⚠️ Yuborish uchun yakunlangan o'yinlar yo'q.",

        # ── Channel Post (I-043) ───────────────────────────────────────────
        "channel_posted": "✅ Yakunlar kanalda e'lon qilindi.",
        "channel_not_set": (
            "⚠️ Kanal sozlanmagan.\n\n"
            "Railway sozlamalarida CHANNEL_ID o'zgaruvchisini qo'shing\n"
            "<i>(masalan: @mychannel yoki -1001234567890)</i>"
        ),

        # ── Buttons ───────────────────────────────────────────────────────
        "btn_my_team": "👥 Mening jamoam",
        "btn_top_scorers": "⚽ Bombardirlar",
        "btn_upcoming_game": "📅 Yaqin o'yin",
        "btn_standings": "🏆 Turnir jadvali",
        "btn_my_stats": "📊 Statistikam",
        "btn_players_list": "👥 O'yinchilar",
        "btn_results": "📋 O'yin natijalari",
        "btn_rules": "📜 Nizom",
        "btn_language": "🌐 Til / Language",
        "btn_profile": "👤 Mening profilim",
        "btn_rate_players": "⭐ O'yinchilarni baholash",
        "btn_back": "🔙 Orqaga",
        "btn_confirm_yes": "✅ Ha, boraman!",
        "btn_confirm_no": "❌ Bora olmayman",
        "btn_confirm_late": "⏰ Kechikaman",
        "btn_register": "✅ Roziman, yozilish",
        "btn_cancel_reg": "❌ Bekor qilish",
        "btn_read_rules": "📜 Nizomni o'qish",
        "btn_join": "✅ Yozilish",
        "btn_decline": "❌ Bormayman",
        "btn_rate_players_start": "⭐ O'yinchilarni baholash",
        "btn_vote_prev": "◀️ Orqaga",
        "btn_vote_next": "▶️ Keyingi",
        "btn_vote_submit": "✅ Ovozlarni yuborish",

        # ── Position labels ───────────────────────────────────────────────
        "pos_gk": "🧤 Darvozabon",
        "pos_def": "🛡 Himoyachi",
        "pos_mid": "⚙️ Yarim himoyachi",
        "pos_fwd": "⚡ Hujumchi",
    },
}
