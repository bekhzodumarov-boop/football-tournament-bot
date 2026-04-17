"""Текст Регламента турнира Football International."""

REGLAMENT_PART1 = """📜 <b>Регламент Football International</b>
<i>Полная инструкция для участников</i>

━━━━━━━━━━━━━━━━━━━━

🆕 <b>1. Регистрация в боте</b>

Прежде чем участвовать в играх — нужно создать профиль.

1. Напиши боту /register
2. Введи своё имя (которое видят другие игроки)
3. Выбери позицию: 🧤 Вратарь / 🛡 Защитник / ⚙️ Полузащитник / ⚡ Нападающий
4. Оцени свой уровень от 1 до 10 — это начальный рейтинг
5. Готово! Ты в системе ✅

💡 <i>Твоё имя из профиля будет отображаться в статистике голов и карточек.</i>

━━━━━━━━━━━━━━━━━━━━

📅 <b>2. Запись на игру</b>

Когда организатор создаёт игровой день — бот автоматически присылает анонс с кнопками.

<b>Шаг 1 — получи анонс</b>
Бот пришлёт сообщение с датой, временем и местом игры.

<b>Шаг 2 — запишись</b>
• Нажми ✅ <b>Записаться</b> → подтверди ознакомление с регламентом
• Нажми ❌ <b>Не пойду</b> → если не можешь прийти

<b>Что значит ⏳ Лист ожидания (Waitlist)?</b>
Если мест уже нет (лимит заполнен) — ты попадаешь в список ожидания.
Как только кто-то откажется — ты автоматически получишь место и уведомление.

<b>Шаг 3 — подтвердить за 2 часа до игры</b>
За 2 часа до начала бот попросит подтвердить явку:
• ✅ <b>Да, иду!</b> — место за тобой
• ❌ <b>Не смогу</b> — место освобождается для следующего из листа ожидания
• ⏰ <b>Опаздываю</b> — придёшь позже, место пока держится

⚠️ <i>Если не ответишь на подтверждение — организатор может исключить тебя из состава.</i>

━━━━━━━━━━━━━━━━━━━━

⭐ <b>3. Рейтинг игроков — зачем и как</b>

Рейтинг нужен для <b>справедливого разделения на команды</b>.
Чем точнее рейтинг — тем равнее команды.

<b>Как формируется рейтинг:</b>

🔹 <b>При регистрации</b> — ты сам оцениваешь себя (1–10). Это <i>провизорный</i> рейтинг.
Он отмечен как "(провизорный)" — значит ещё мало данных.

🔹 <b>Голосование игроков</b> — после каждой игры организатор запускает опрос.
Каждый участник оценивает других от 1 до 10.
Система усредняет оценки и плавно обновляет рейтинги (60% старый + 40% новый).

🔹 <b>Защита от накруток</b> — если чья-то оценка сильно отличается от остальных (аномалия),
она помечается и не влияет на результат.

💡 <i>Рейтинг — не ранжирование "лучший/худший". Это инструмент балансировки команд.</i>"""


REGLAMENT_PART2 = """📜 <b>Регламент (продолжение)</b>

━━━━━━━━━━━━━━━━━━━━

👥 <b>4. Формирование команд</b>

После закрытия записи организатор разбивает участников на команды.

<b>Алгоритм автоматической балансировки:</b>
1. Вратарей распределяют по одному на каждую команду
2. Остальные игроки сортируются по рейтингу
3. Распределение идёт методом "змейки" (сильнейший → команда 1, следующий → команда 2, ..., потом обратно)
4. Итог: команды максимально равны по суммарному рейтингу

<b>Команды получают цвет и название:</b>
⚪ Белые / 🟡 Жёлтые / 🔴 Красные / 🔵 Синие (и другие)

Каждый игрок получает уведомление в боте: в какой команде играет и с кем.

━━━━━━━━━━━━━━━━━━━━

⚽ <b>5. Формат турнира</b>

<b>Групповой этап:</b>
• Каждая команда играет с каждой дважды
• 4 команды = 12 матчей, 3 команды = 6 матчей
• Продолжительность матча: 6 минут (или до N голов — зависит от настройки)

<b>Начисление очков:</b>
• 🟢 Победа — 3 очка
• 🟡 Ничья — 1 очко
• 🔴 Поражение — 0 очков

<b>При равенстве очков:</b>
1. Личный результат между командами
2. Разница голов (забитые − пропущенные)
3. Больше забитых голов
4. Меньше жёлтых карточек

<b>Плей-офф (при 4 командах):</b>
🏆 Полуфинал 1: 1-е место vs 4-е место
🏆 Полуфинал 2: 2-е место vs 3-е место
🥉 Матч за 3-е место: проигравшие полуфиналов
🏆🏆 Финал: победители полуфиналов

<b>В плей-офф при ничьей</b> победитель определяется:
1. Серией послематчевых голов до первого промаха (penalty shootout)
2. Либо по правилу "внезапная смерть" — кто первый забьёт

━━━━━━━━━━━━━━━━━━━━

🟨🟥 <b>6. Карточки и дисквалификация</b>

Судья фиксирует нарушения через бот в режиме реального времени.

<b>Жёлтая карточка 🟨</b>
• Предупреждение за нарушение правил
• Не влечёт автоматических последствий
• Учитывается при равенстве очков в таблице

<b>Красная карточка 🟥</b>
• Удаление с поля немедленно
• <b>Дисквалификация:</b> игрок не играет в текущем и следующем матче игрового дня
• Если игрок уже имел красную карточку ранее в этот день — судья получает предупреждение

━━━━━━━━━━━━━━━━━━━━

🔄 <b>7. Замены</b>

Замены доступны только в матчах "по времени" (не в формате "до N голов").

• Судья нажимает кнопку 🔄 <b>Замена</b> в панели матча
• Выбирает команду → игрока, который выходит → игрока, который заходит
• Замена <b>не ограничена</b> по количеству
• Можно ввести игрока из скамейки <b>или перевести из другой команды</b> (помечается *)

━━━━━━━━━━━━━━━━━━━━

💰 <b>8. Оплата взноса</b>

• Размер взноса определяет организатор (расходы / кол-во игроков)
• После игры бот рассылает сумму взноса каждому участнику
• Оплата — наличными организатору или через договорённый способ
• Факт оплаты отмечает организатор в админке

━━━━━━━━━━━━━━━━━━━━

❓ <b>9. Частые вопросы</b>

<b>Как посмотреть таблицу во время игры?</b>
Главное меню → 🏆 Таблица турнира

<b>Как узнать свою статистику?</b>
Главное меню → 📊 Моя статистика

<b>Что если я записался, но не смогу прийти?</b>
Сообщи организатору как можно раньше — место освободится для другого игрока.

<b>Что такое "провизорный рейтинг"?</b>
У новых игроков мало данных — рейтинг провизорный (временный).
После первого голосования он станет постоянным.

<b>Можно ли оспорить гол или карточку?</b>
Только через судью на поле. В боте постфактум можно добавить событие, но не удалить.

⚠️ <i>Регистрируясь на игру, участник принимает условия настоящего регламента.</i>"""


# Короткое описание для подтверждения записи
REGLAMENT_AGREEMENT = (
    "📜 Продолжив регистрацию, вы соглашаетесь с "
    "<b>Регламентом турнира</b>.\n"
    "Ознакомиться: /rules"
)


REGLAMENT_PART1_EN = """📜 <b>Football International — Rules</b>
<i>Full guide for participants</i>

━━━━━━━━━━━━━━━━━━━━

🆕 <b>1. Bot Registration</b>

Before joining games you need to create a profile.

1. Send the bot /register
2. Enter your name (visible to other players)
3. Choose your position: 🧤 Goalkeeper / 🛡 Defender / ⚙️ Midfielder / ⚡ Forward
4. Rate your skill from 1 to 10 — this is your starting rating
5. Done! You're in the system ✅

💡 <i>Your profile name will appear in goal and card stats.</i>

━━━━━━━━━━━━━━━━━━━━

📅 <b>2. Signing Up for a Game</b>

When an organizer creates a game day, the bot automatically sends an announcement with buttons.

<b>Step 1 — receive the announcement</b>
The bot will send a message with the date, time, and location.

<b>Step 2 — register</b>
• Tap ✅ <b>Join</b> → confirm you've read the rules
• Tap ❌ <b>Not going</b> → if you can't attend

<b>What is ⏳ Waitlist?</b>
If spots are full (limit reached) — you're placed on the waitlist.
As soon as someone drops out — you automatically get a spot and a notification.

<b>Step 3 — confirm 2 hours before the game</b>
2 hours before kickoff the bot will ask you to confirm attendance:
• ✅ <b>Yes, I'm in!</b> — your spot is secured
• ❌ <b>Can't make it</b> — your spot is passed to the next person on the waitlist
• ⏰ <b>Running late</b> — you'll arrive late, spot is temporarily held

⚠️ <i>If you don't respond to the confirmation — the organizer may remove you from the roster.</i>

━━━━━━━━━━━━━━━━━━━━

⭐ <b>3. Player Ratings — Why and How</b>

Ratings are used for <b>fair team balancing</b>.
The more accurate the ratings — the more even the teams.

<b>How ratings are formed:</b>

🔹 <b>At registration</b> — you rate yourself (1–10). This is a <i>provisional</i> rating.
It shows as "(provisional)" — meaning there's not enough data yet.

🔹 <b>Player voting</b> — after each game the organizer starts a vote.
Each participant rates others from 1 to 10.
The system averages the scores and gradually updates ratings (60% old + 40% new).

🔹 <b>Anti-manipulation protection</b> — if someone's score is far from the rest (anomaly),
it's flagged and doesn't affect the result.

💡 <i>Rating is not a "best/worst" ranking. It's a team balancing tool.</i>"""


REGLAMENT_PART2_EN = """📜 <b>Rules (continued)</b>

━━━━━━━━━━━━━━━━━━━━

👥 <b>4. Team Formation</b>

After registration closes, the organizer splits participants into teams.

<b>Auto-balancing algorithm:</b>
1. Goalkeepers are distributed — one per team
2. Other players are sorted by rating
3. Distribution uses the "snake" method (best → team 1, next → team 2, ..., then back)
4. Result: teams are as equal as possible by total rating

<b>Teams receive a color and name:</b>
⚪ White / 🟡 Yellow / 🔴 Red / 🔵 Blue (and others)

Each player receives a bot notification: which team they're on and their teammates.

━━━━━━━━━━━━━━━━━━━━

⚽ <b>5. Tournament Format</b>

<b>Group stage:</b>
• Each team plays every other team twice
• 4 teams = 12 matches, 3 teams = 6 matches
• Match duration: 6 minutes (or until N goals — depends on settings)

<b>Points:</b>
• 🟢 Win — 3 points
• 🟡 Draw — 1 point
• 🔴 Loss — 0 points

<b>Tiebreakers:</b>
1. Head-to-head result
2. Goal difference (scored − conceded)
3. More goals scored
4. Fewer yellow cards

<b>Playoff (4 teams):</b>
🏆 Semifinal 1: 1st vs 4th place
🏆 Semifinal 2: 2nd vs 3rd place
🥉 3rd place match: semifinal losers
🏆🏆 Final: semifinal winners

<b>In playoff ties</b> the winner is decided by:
1. Penalty shootout (first miss loses)
2. Or sudden death — first to score wins

━━━━━━━━━━━━━━━━━━━━

🟨🟥 <b>6. Cards and Disqualifications</b>

The referee records fouls via the bot in real time.

<b>Yellow card 🟨</b>
• Warning for a rule violation
• No automatic consequences
• Counts as a tiebreaker in the standings

<b>Red card 🟥</b>
• Immediate dismissal from the field
• <b>Disqualification:</b> player misses the current and next match of the game day
• If the player already had a red card earlier that day — the referee receives a warning

━━━━━━━━━━━━━━━━━━━━

🔄 <b>7. Substitutions</b>

Substitutions are only available in timed matches (not in "first to N goals" format).

• The referee taps 🔄 <b>Sub</b> in the match panel
• Selects the team → player going off → player coming on
• Substitutions are <b>unlimited</b>
• You can bring in a player from the bench <b>or transfer from another team</b> (marked *)

━━━━━━━━━━━━━━━━━━━━

💰 <b>8. Payment</b>

• The fee amount is set by the organizer (costs / number of players)
• After the game the bot sends each participant the fee amount
• Payment is made in cash to the organizer or via an agreed method
• The organizer marks payment in the admin panel

━━━━━━━━━━━━━━━━━━━━

❓ <b>9. FAQ</b>

<b>How do I check the standings during the game?</b>
Main menu → 🏆 Standings

<b>How do I see my stats?</b>
Main menu → 📊 My Stats

<b>What if I signed up but can't come?</b>
Let the organizer know as early as possible — the spot will open up for another player.

<b>What is a "provisional rating"?</b>
New players don't have enough data yet — the rating is provisional (temporary).
After the first vote it becomes permanent.

<b>Can I dispute a goal or card?</b>
Only through the referee on the field. Events can be added in the bot after the fact, but not deleted.

⚠️ <i>By registering for a game, the participant accepts these rules.</i>"""


REGLAMENT_AGREEMENT_EN = (
    "📜 By continuing registration, you agree to the "
    "<b>Tournament Rules</b>.\n"
    "Read the rules: /rules"
)
