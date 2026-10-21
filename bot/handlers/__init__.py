from aiogram import Router

from .admin import build_admin_router
from .user import router as user_router


def build_router(admin_ids: frozenset[int]) -> Router:
    root = Router(name="root")
    # админский роутер первым: в пользовательском есть обработчик «любой текст»
    root.include_router(build_admin_router(admin_ids))
    root.include_router(user_router)
    return root
