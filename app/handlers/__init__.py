from aiogram import Dispatcher
from .common import router as common_router
from .registration import router as registration_router
from .game_day import router as game_day_router
from .admin import router as admin_router
from .admin_extra import router as admin_extra_router
from .referee import router as referee_router
from .developer import router as developer_router


def register_all_handlers(dp: Dispatcher):
    # common первым — /start и /cancel работают из любого FSM-состояния
    dp.include_router(common_router)
    dp.include_router(registration_router)
    dp.include_router(game_day_router)
    dp.include_router(admin_router)
    dp.include_router(admin_extra_router)
    dp.include_router(referee_router)
    dp.include_router(developer_router)
