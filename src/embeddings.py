"""Fase 3 — Generación de embeddings semánticos con text-embedding-004 e indexado en ChromaDB."""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import chromadb
import google.generativeai as genai
from tqdm import tqdm

from src.config import CHROMA_DB_PATH, DATA_DIR, GEMINI_API_KEY

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "models/gemini-embedding-2"
EMBEDDING_DIMENSION = 3072
BATCH_SIZE = 100
COLLECTION_NAME = "cinematch_movies"
CATALOG_FILENAME = "catalog.json"
TASK_TYPE_INDEX = "retrieval_document"
TASK_TYPE_QUERY = "retrieval_query"
BATCH_DELAY_SECONDS = 15  # pausa entre batches para no saturar tier free
MAX_RETRIES = 3           # reintentos por batch ante error 429


class EmbeddingsError(Exception):
    pass


class EmbeddingsBuilder:
    """Construye y gestiona los embeddings semánticos del catálogo de películas."""

    def __init__(self, api_key: Optional[str] = None, db_path: Optional[str] = None) -> None:
        genai.configure(api_key=api_key or GEMINI_API_KEY)

        path = db_path or CHROMA_DB_PATH
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._stats: dict = {"fetched": 0, "embedded": 0, "skipped": 0, "errors": 0}

    # ── Carga ──────────────────────────────────────────────────────────────────

    def load_catalog(self, catalog_path: Path) -> list[dict]:
        if not catalog_path.exists():
            raise FileNotFoundError(
                f"Catálogo no encontrado en '{catalog_path}'. "
                "Ejecuta build_catalog.py primero."
            )
        with catalog_path.open(encoding="utf-8") as f:
            return json.load(f)

    # ── Construcción de texto ──────────────────────────────────────────────────

    def build_text_for_embedding(self, movie: dict) -> str:
        lines: list[str] = []
        lines.append(f"Título: {movie['title']}")
        lines.append(f"Año: {movie['release_year']}")
        if movie.get("director"):
            lines.append(f"Director: {movie['director']}")
        if movie.get("genres"):
            lines.append(f"Géneros: {', '.join(movie['genres'])}")
        if movie.get("overview"):
            lines.append(f"Sinopsis: {movie['overview']}")
        if movie.get("tagline"):
            lines.append(f"Tagline: {movie['tagline']}")
        if movie.get("keywords"):
            lines.append(f"Palabras clave: {', '.join(movie['keywords'])}")
        return "\n".join(lines)

    # ── ChromaDB ───────────────────────────────────────────────────────────────

    def get_existing_ids(self) -> set[str]:
        result = self._collection.get(include=[])
        return set(result["ids"])

    def _metadata_for_movie(self, movie: dict) -> dict:
        return {
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title", ""),
            "release_year": movie.get("release_year", 0),
            "director": movie.get("director", ""),
            "genres": ", ".join(movie.get("genres", [])),
            "cast_top3": ", ".join(movie.get("cast_top3", [])),
            "runtime": movie.get("runtime", 0),
            "vote_average": movie.get("vote_average", 0.0),
            "vote_count": movie.get("vote_count", 0),
            "original_language": movie.get("original_language", ""),
            "poster_url": movie.get("poster_url", ""),
            "tagline": movie.get("tagline", ""),
        }

    # ── API Gemini ─────────────────────────────────────────────────────────────

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para un batch de textos con reintentos."""
        import google.api_core.exceptions

        for attempt in range(MAX_RETRIES):
            try:
                result = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=texts,
                    task_type=TASK_TYPE_INDEX,
                )
                embedding = result["embedding"]
                if texts and not isinstance(embedding[0], list):
                    return [embedding]
                return embedding
            except google.api_core.exceptions.ResourceExhausted as exc:
                if attempt < MAX_RETRIES - 1:
                    wait_time = BATCH_DELAY_SECONDS * (2 ** attempt)
                    logger.warning(
                        "Rate limit alcanzado, reintento %d/%d en %ds...",
                        attempt + 1, MAX_RETRIES, wait_time,
                    )
                    time.sleep(wait_time)
                else:
                    logger.error("Rate limit persistente tras %d intentos.", MAX_RETRIES)
                    raise EmbeddingsError(f"Rate limit no superado: {exc}") from exc
            except Exception as exc:
                raise EmbeddingsError(f"Error en embed_content: {exc}") from exc

    # ── Pipeline principal ─────────────────────────────────────────────────────

    def build(
        self,
        catalog_path: Optional[Path] = None,
        resume: bool = True,
    ) -> dict:
        """Genera embeddings para todas las películas pendientes y los guarda en ChromaDB.

        Args:
            catalog_path: Ruta al catalog.json. Por defecto DATA_DIR/CATALOG_FILENAME.
            resume: Si True, omite las películas ya indexadas en ChromaDB.

        Returns:
            Diccionario con estadísticas: fetched, embedded, skipped, errors.
        """
        if catalog_path is None:
            catalog_path = Path(DATA_DIR) / CATALOG_FILENAME

        movies = self.load_catalog(catalog_path)
        self._stats["fetched"] = len(movies)

        if resume:
            existing = self.get_existing_ids()
            pending = [m for m in movies if str(m["id"]) not in existing]
            self._stats["skipped"] = len(movies) - len(pending)
            logger.info(
                "Retomando: %d ya indexadas, %d pendientes.",
                self._stats["skipped"],
                len(pending),
            )
        else:
            pending = movies

        if not pending:
            logger.info("Nada que procesar — todas las películas ya están indexadas.")
            self._print_stats()
            return self._stats

        chunks = [pending[i : i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]

        with tqdm(total=len(pending), desc="Embeddings", unit="película") as bar:
            for i, batch in enumerate(chunks):
                try:
                    textos = [self.build_text_for_embedding(m) for m in batch]
                    embeddings = self.embed_batch(textos)
                    self._collection.add(
                        ids=[str(m["id"]) for m in batch],
                        embeddings=embeddings,
                        documents=textos,
                        metadatas=[self._metadata_for_movie(m) for m in batch],
                    )
                    self._stats["embedded"] += len(batch)
                except EmbeddingsError as exc:
                    logger.error(
                        "Batch %d falló definitivamente (primer ID %s): %s",
                        i + 1, batch[0]["id"], exc,
                    )
                    self._stats["errors"] += len(batch)
                except Exception as exc:
                    logger.error(
                        "Error inesperado en batch %d (primer ID %s): %s",
                        i + 1, batch[0]["id"], exc,
                    )
                    self._stats["errors"] += len(batch)
                finally:
                    bar.update(len(batch))
                    if i < len(chunks) - 1:
                        time.sleep(BATCH_DELAY_SECONDS)

        self._print_stats()
        return self._stats

    # ── Búsqueda (Fase 4) ──────────────────────────────────────────────────────

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Busca películas semánticamente similares a la consulta.

        Args:
            query: Texto libre de búsqueda.
            n_results: Número de resultados a retornar.

        Returns:
            Lista de dicts con id, document, metadata y distance.
        """
        vec = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=query,
            task_type=TASK_TYPE_QUERY,
        )["embedding"]

        res = self._collection.query(
            query_embeddings=[vec],
            n_results=n_results,
        )

        results = []
        for i, doc_id in enumerate(res["ids"][0]):
            results.append({
                "id": doc_id,
                "document": res["documents"][0][i],
                "metadata": res["metadatas"][0][i],
                "distance": res["distances"][0][i],
            })
        return results

    # ── Utilidades ─────────────────────────────────────────────────────────────

    def reset_collection(self) -> None:
        self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Colección '%s' reiniciada.", COLLECTION_NAME)

    def _print_stats(self) -> None:
        logger.info(
            "Stats — catálogo: %d | ya indexadas: %d | nuevas: %d | errores: %d",
            self._stats["fetched"],
            self._stats["skipped"],
            self._stats["embedded"],
            self._stats["errors"],
        )
