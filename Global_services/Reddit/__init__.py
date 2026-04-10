# -*- coding: utf-8 -*-
"""
Reddit — переиспользуемый пакет для работы с Reddit API.

Экспортирует:
    RedditClient       — async клиент (anonymous + OAuth2)
    RedditPost         — dataclass поста
    RedditComment      — dataclass комментария
    create_reddit_client_from_env — фабрика из .env
"""

from .reddit_client import (
    RedditClient,
    RedditPost,
    RedditComment,
    create_reddit_client_from_env,
)

__all__ = [
    "RedditClient",
    "RedditPost",
    "RedditComment",
    "create_reddit_client_from_env",
]
