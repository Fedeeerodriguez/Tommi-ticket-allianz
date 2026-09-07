"""Persistencia: repositorio enchufable (Postgres/Supabase o SQLite dev)."""
from .repo import Repositorio, RepositorioPostgres, RepositorioSQLite, get_repo

__all__ = ["Repositorio", "RepositorioPostgres", "RepositorioSQLite", "get_repo"]
