"""Construcción del catálogo de películas desde TMDB — CineMatch Fase 2."""

import json
import logging
from math import ceil
from pathlib import Path
from typing import Optional

import pandas as pd
from tqdm import tqdm

from src.config import DATA_DIR
from src.tmdb_client import TMDBClient, TMDBError

logger = logging.getLogger(__name__)

TARGET_SIZE = 3000
TOP_RATED_QUOTA = 1500
POPULAR_QUOTA = 900
GENRES_QUOTA = 600
MIN_OVERVIEW_LENGTH = 20
MIN_VOTE_COUNT = 100
MIN_RUNTIME = 40
ALLOWED_LANGUAGES = ["en", "es", "fr", "it", "de", "ja", "ko", "pt", "ru", "zh", "hi", "da", "sv"]
CHECKPOINT_INTERVAL = 100
CATALOG_FILENAME = "catalog.json"
CHECKPOINT_FILENAME = "catalog_checkpoint.json"


class CatalogBuilder:
    """Descarga, enriquece y filtra un catálogo de películas desde TMDB.

    Combina tres fuentes para equilibrar calidad histórica, relevancia
    actual y diversidad de géneros:
    - top_rated  → 1 500 películas (calidad histórica)
    - popular    →   900 películas (relevancia actual)
    - por género →   600 películas (diversidad)

    Args:
        client: Instancia de TMDBClient ya configurada.
        target_size: Número objetivo de películas en el catálogo final.
    """

    def __init__(self, client: TMDBClient, target_size: int = TARGET_SIZE) -> None:
        self._client = client
        self._target_size = target_size
        self._catalog: dict[int, dict] = {}
        self._stats: dict[str, int] = {
            "fetched": 0,
            "enriched": 0,
            "kept": 0,
            "rejected_overview": 0,
            "rejected_votes": 0,
            "rejected_runtime": 0,
            "rejected_language": 0,
            "errors": 0,
        }

    # -----------------------------------------------------------------------
    # Método principal
    # -----------------------------------------------------------------------

    def build(self) -> list[dict]:
        """Orquesta la descarga, enriquecimiento y filtrado del catálogo.

        Returns:
            Lista de dicts con 15 campos por película, ya filtrada por calidad.
        """
        logger.info("=== Iniciando construcción del catálogo (objetivo: %d) ===", self._target_size)
        scale = self._target_size / TARGET_SIZE
        self._fetch_top_rated(max(1, round(TOP_RATED_QUOTA * scale)))
        self._fetch_popular(max(1, round(POPULAR_QUOTA * scale)))
        self._fetch_by_genres(max(1, round(GENRES_QUOTA * scale)))

        logger.info("Total de películas únicas antes de enriquecer: %d", len(self._catalog))

        self._enrich_all_movies()
        result = self._filter_quality()
        self._print_stats(result)
        return result

    # -----------------------------------------------------------------------
    # Métodos de descarga (fetch)
    # -----------------------------------------------------------------------

    def _store_basic(self, movie: dict) -> bool:
        """Intenta almacenar una película con campos base. Retorna True si es nueva."""
        mid = movie.get("id")
        if not mid or mid in self._catalog:
            return False
        overview = movie.get("overview") or ""
        if len(overview) < MIN_OVERVIEW_LENGTH or movie.get("vote_count", 0) < MIN_VOTE_COUNT:
            return False
        release_date = movie.get("release_date") or ""
        try:
            release_year = int(release_date[:4])
        except (ValueError, TypeError):
            release_year = 0
        self._catalog[mid] = {
            "id": mid,
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title", ""),
            "release_year": release_year,
            "overview": overview,
            "poster_path": movie.get("poster_path"),
            "vote_average": movie.get("vote_average", 0.0),
            "vote_count": movie.get("vote_count", 0),
            "original_language": movie.get("original_language", ""),
            "genre_ids": movie.get("genre_ids", []),
            # campos a rellenar en enriquecimiento:
            "genres": [],
            "runtime": None,
            "director": "",
            "cast_top3": [],
            "poster_url": "",
            "tagline": "",
            "keywords": [],
            "_enrich_failed": False,
        }
        self._stats["fetched"] += 1
        return True

    def _fetch_top_rated(self, quota: int = TOP_RATED_QUOTA) -> None:
        logger.info("Descargando top_rated (objetivo: %d)…", quota)
        added = 0
        page = 1
        with tqdm(total=quota, desc="top_rated", unit="pelic") as pbar:
            while added < quota:
                data = self._client.get_top_rated_movies(page=page)
                results = data.get("results", [])
                if not results:
                    break
                new_in_page = 0
                for m in results:
                    if self._store_basic(m):
                        added += 1
                        new_in_page += 1
                        pbar.update(1)
                        if added >= quota:
                            break
                if new_in_page == 0:
                    logger.debug("top_rated: sin IDs nuevos en página %d, terminando.", page)
                    break
                if page >= data.get("total_pages", page):
                    break
                page += 1

    def _fetch_popular(self, quota: int = POPULAR_QUOTA) -> None:
        logger.info("Descargando popular (objetivo: %d)…", quota)
        added = 0
        page = 1
        with tqdm(total=quota, desc="popular", unit="pelic") as pbar:
            while added < quota:
                data = self._client.get_popular_movies(page=page)
                results = data.get("results", [])
                if not results:
                    break
                new_in_page = 0
                for m in results:
                    if self._store_basic(m):
                        added += 1
                        new_in_page += 1
                        pbar.update(1)
                        if added >= quota:
                            break
                if new_in_page == 0:
                    logger.debug("popular: sin IDs nuevos en página %d, terminando.", page)
                    break
                if page >= data.get("total_pages", page):
                    break
                page += 1

    def _fetch_by_genres(self, quota: int = GENRES_QUOTA) -> None:
        logger.info("Descargando por géneros (objetivo: %d)…", quota)
        genres = self._client.get_genres()
        per_genre = ceil(quota / len(genres)) if genres else quota
        total_added = 0

        for sort_by in ("vote_average.desc", "popularity.desc"):
            if total_added >= quota:
                break
            for genre in tqdm(genres, desc=f"géneros ({sort_by})", unit="género"):
                if total_added >= quota:
                    break
                genre_added = 0
                page = 1
                while genre_added < per_genre:
                    try:
                        data = self._client.discover_movies(**{
                            "with_genres": str(genre["id"]),
                            "sort_by": sort_by,
                            "vote_count.gte": MIN_VOTE_COUNT,
                            "page": page,
                        })
                    except TMDBError as exc:
                        logger.warning("discover_movies género %s falló: %s", genre["name"], exc)
                        break
                    results = data.get("results", [])
                    if not results:
                        break
                    new_in_page = 0
                    for m in results:
                        if self._store_basic(m):
                            genre_added += 1
                            total_added += 1
                            new_in_page += 1
                            if genre_added >= per_genre or total_added >= quota:
                                break
                    if new_in_page == 0 or page >= data.get("total_pages", page):
                        break
                    page += 1

        logger.info("Películas tras fetch por géneros: %d", len(self._catalog))

    # -----------------------------------------------------------------------
    # Enriquecimiento
    # -----------------------------------------------------------------------

    def _enrich_all_movies(self) -> None:
        logger.info("Enriqueciendo %d películas (3 req/película)…", len(self._catalog))
        checkpoint_path = Path(DATA_DIR) / CHECKPOINT_FILENAME
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        processed = 0

        for mid, entry in tqdm(self._catalog.items(), desc="Enriqueciendo", unit="pelic"):
            try:
                details = self._client.get_movie_details(mid)
                credits = self._client.get_movie_credits(mid)
                keywords = self._client.get_movie_keywords(mid)
            except TMDBError as exc:
                logger.warning("Error enriqueciendo película %d: %s", mid, exc)
                entry["_enrich_failed"] = True
                self._stats["errors"] += 1
                processed += 1
                continue

            entry["runtime"] = details.get("runtime")
            entry["tagline"] = details.get("tagline") or ""
            entry["overview"] = details.get("overview") or entry["overview"]
            entry["title"] = details.get("title") or entry["title"]
            entry["genres"] = [g["name"] for g in details.get("genres", [])]

            director = next(
                (p["name"] for p in credits.get("crew", []) if p.get("job") == "Director"),
                "",
            )
            entry["director"] = director
            entry["cast_top3"] = [p["name"] for p in credits.get("cast", [])[:3]]
            entry["keywords"] = keywords
            entry["poster_url"] = self._client.build_poster_url(entry.get("poster_path")) or ""

            self._stats["enriched"] += 1
            processed += 1

            if processed % CHECKPOINT_INTERVAL == 0:
                self._save_checkpoint(checkpoint_path)

    def _save_checkpoint(self, path: Path) -> None:
        snapshot = [self._clean_entry(e) for e in self._catalog.values() if not e.get("_enrich_failed")]
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.warning("No se pudo guardar checkpoint: %s", exc)

    # -----------------------------------------------------------------------
    # Filtrado de calidad
    # -----------------------------------------------------------------------

    def _filter_quality(self) -> list[dict]:
        result = []
        for entry in self._catalog.values():
            if entry.get("_enrich_failed"):
                continue
            if len(entry.get("overview", "")) < MIN_OVERVIEW_LENGTH:
                self._stats["rejected_overview"] += 1
                continue
            if entry.get("vote_count", 0) < MIN_VOTE_COUNT:
                self._stats["rejected_votes"] += 1
                continue
            runtime = entry.get("runtime")
            if runtime is None or runtime < MIN_RUNTIME:
                self._stats["rejected_runtime"] += 1
                continue
            if entry.get("original_language") not in ALLOWED_LANGUAGES:
                self._stats["rejected_language"] += 1
                continue
            result.append(self._clean_entry(entry))
        self._stats["kept"] = len(result)
        return result

    @staticmethod
    def _clean_entry(entry: dict) -> dict:
        """Retorna una copia sin campos internos (_enrich_failed, poster_path, genre_ids)."""
        skip = {"_enrich_failed", "poster_path", "genre_ids"}
        return {k: v for k, v in entry.items() if k not in skip}

    # -----------------------------------------------------------------------
    # Stats y persistencia
    # -----------------------------------------------------------------------

    def _print_stats(self, result: list[dict]) -> None:
        s = self._stats
        logger.info("--- Estadísticas del catálogo ---")
        logger.info("Descargadas: %d | Enriquecidas: %d | En catálogo: %d",
                    s["fetched"], s["enriched"], s["kept"])
        logger.info("Rechazos — overview: %d | votos: %d | runtime: %d | idioma: %d | errores: %d",
                    s["rejected_overview"], s["rejected_votes"],
                    s["rejected_runtime"], s["rejected_language"], s["errors"])
        if not result:
            return
        df = pd.DataFrame(result)
        if "original_language" in df.columns:
            top_langs = df["original_language"].value_counts().head(5)
            logger.info("Top 5 idiomas:\n%s", top_langs.to_string())
        if "genres" in df.columns:
            from collections import Counter
            all_genres = [g for row in df["genres"] for g in row]
            top_genres = Counter(all_genres).most_common(5)
            logger.info("Top 5 géneros: %s", top_genres)
        if "release_year" in df.columns:
            valid_years = df["release_year"].replace(0, pd.NA).dropna()
            if not valid_years.empty:
                logger.info("Rango de años: %d – %d", int(valid_years.min()), int(valid_years.max()))

    def save(self, output_path: Path) -> None:
        """Guarda el catálogo actual en disco como JSON.

        Args:
            output_path: Ruta completa del archivo de salida.
        """
        catalog_list = [self._clean_entry(e) for e in self._catalog.values()
                        if not e.get("_enrich_failed")]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(catalog_list, f, indent=2, ensure_ascii=False)
        logger.info("Catálogo guardado: %s (%d películas)", output_path, len(catalog_list))
