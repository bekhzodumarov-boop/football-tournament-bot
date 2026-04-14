from aiogram import Dispatcher
from .common import router as common_router
from .registration import router as registration_router
from .game_day import router as game_day_router
from .admin import router as admin_router


def register_all_handlers(dp: Dispatcher):
    dp.include_router(registration_router)
    dp.include_router(game_day_router)
    dp.include_router(admin_router)
    dp.include_router(common_router)  # common последним (catch-all)
