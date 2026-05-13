"""Fase 4 — Asistente conversacional basado en Gemini Flash con RAG semántico."""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import pandas as pd
from google import genai
from google.genai import types

from src.config import DATA_DIR, GEMINI_API_KEY
from src.embeddings import EmbeddingsBuilder
from src.tmdb_client import TMDBClient

logger = logging.getLogger(__name__)

CHAT_MODEL = "gemini-2.5-flash-lite"
CATALOG_FILENAME = "catalog.json"
PROMPTS_DIR = "prompts"
PERSONALITY_FILE = "personality.md"
SYSTEM_PROMPT_FILE = "system_prompt.md"
MAX_HISTORY_MESSAGES = 20

# ── Tool declarations ──────────────────────────────────────────────────────────

_semantic_search_fn = types.FunctionDeclaration(
    name="semantic_search",
    description=(
        "Busca películas por similitud semántica con la consulta. "
        "Úsala para peticiones basadas en estado de ánimo, sensaciones, "
        "conceptos abstractos o 'algo parecido a X'."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(
                type=types.Type.STRING,
                description="Texto libre de búsqueda semántica",
            ),
            "n_results": types.Schema(
                type=types.Type.INTEGER,
                description="Número de resultados a retornar (por defecto 5)",
            ),
        },
        required=["query"],
    ),
)

_structured_search_fn = types.FunctionDeclaration(
    name="structured_search",
    description=(
        "Filtra el catálogo por criterios exactos: género, rango de año, "
        "calificación mínima o duración máxima. Úsala cuando el usuario "
        "especifica restricciones concretas."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "genre": types.Schema(
                type=types.Type.STRING,
                description="Género cinematográfico (ej: 'Acción', 'Drama')",
            ),
            "year_min": types.Schema(
                type=types.Type.INTEGER,
                description="Año de lanzamiento mínimo (inclusive)",
            ),
            "year_max": types.Schema(
                type=types.Type.INTEGER,
                description="Año de lanzamiento máximo (inclusive)",
            ),
            "min_rating": types.Schema(
                type=types.Type.NUMBER,
                description="Calificación TMDB mínima (0.0 a 10.0)",
            ),
            "max_runtime": types.Schema(
                type=types.Type.INTEGER,
                description="Duración máxima en minutos",
            ),
        },
        required=[],
    ),
)

_lookup_movie_fn = types.FunctionDeclaration(
    name="lookup_movie",
    description=(
        "Obtiene detalles actualizados de una película específica desde TMDB. "
        "Úsala cuando el usuario pregunta por un título concreto."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(
                type=types.Type.STRING,
                description="Título de la película a buscar",
            ),
        },
        required=["title"],
    ),
)


def _to_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if f != f else f  # NaN check: NaN != NaN
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    try:
        f = float(v)
        return None if f != f else int(f)
    except (TypeError, ValueError):
        return None


class CineMatchAssistant:
    """Asistente conversacional de recomendaciones de películas."""

    def __init__(self) -> None:
        self._system_instruction = self._build_system_instruction()
        self._genai_client = genai.Client(api_key=GEMINI_API_KEY)
        self._embeddings = EmbeddingsBuilder()
        self._tmdb = TMDBClient()

        catalog_path = Path(__file__).parents[1] / DATA_DIR / CATALOG_FILENAME
        with catalog_path.open(encoding="utf-8") as f:
            catalog_data = json.load(f)

        self._catalog_df = pd.DataFrame(catalog_data)
        self._catalog_index: dict[str, dict] = {
            str(m["id"]): m for m in catalog_data
        }

        self._tools = [types.Tool(function_declarations=[
            _semantic_search_fn,
            _structured_search_fn,
            _lookup_movie_fn,
        ])]

        self._history: list[types.Content] = []
        self._shown_ids: set[str] = set()

    def _build_system_instruction(self) -> str:
        prompts_dir = Path(__file__).parents[1] / PROMPTS_DIR
        personality = (prompts_dir / PERSONALITY_FILE).read_text(encoding="utf-8")
        system_prompt = (prompts_dir / SYSTEM_PROMPT_FILE).read_text(encoding="utf-8")
        return f"{personality}\n\n---\n\n{system_prompt}"

    # ── Herramientas de búsqueda ───────────────────────────────────────────────

    def _semantic_search(self, query: str, n_results: int = 5) -> list[dict]:
        try:
            raw = self._embeddings.search(query, n_results)
        except Exception as exc:
            logger.error("semantic_search falló: %s", exc)
            return []

        results = []
        for item in raw:
            meta = item["metadata"]
            catalog_entry = self._catalog_index.get(str(item["id"]), {})
            results.append({
                "id": str(item["id"]),
                "title": str(meta.get("title") or ""),
                "year": _to_int(meta.get("release_year")),
                "director": str(meta.get("director") or ""),
                "genres": str(meta.get("genres") or ""),
                "overview": str(catalog_entry.get("overview") or ""),
                "vote_average": _to_float(meta.get("vote_average")),
                "runtime": _to_int(meta.get("runtime")),
                "poster_url": str(meta.get("poster_url") or ""),
                "distance": float(item["distance"]),
            })
        return results

    def _structured_search(self, filters: dict) -> list[dict]:
        try:
            df = self._catalog_df.copy()

            genre = filters.get("genre")
            if genre:
                df = df[df["genres"].apply(
                    lambda gs: isinstance(gs, list) and any(
                        genre.lower() in g.lower() for g in gs
                    )
                )]

            year_min = filters.get("year_min")
            if year_min is not None:
                df = df[df["release_year"] >= int(year_min)]

            year_max = filters.get("year_max")
            if year_max is not None:
                df = df[df["release_year"] <= int(year_max)]

            min_rating = filters.get("min_rating")
            if min_rating is not None:
                df = df[df["vote_average"] >= float(min_rating)]

            max_runtime = filters.get("max_runtime")
            if max_runtime is not None:
                df = df[df["runtime"].notna() & (df["runtime"] <= int(max_runtime))]

            df = df.sort_values("vote_average", ascending=False).head(10)

            results = []
            for _, row in df.iterrows():
                genres_val = row.get("genres", [])
                results.append({
                    "id": str(int(row["id"])),
                    "title": str(row.get("title") or ""),
                    "year": _to_int(row.get("release_year")),
                    "director": str(row.get("director") or ""),
                    "genres": (
                        ", ".join(genres_val)
                        if isinstance(genres_val, list)
                        else str(genres_val)
                    ),
                    "overview": str(row.get("overview") or ""),
                    "vote_average": _to_float(row.get("vote_average")),
                    "runtime": _to_int(row.get("runtime")),
                    "poster_url": str(row.get("poster_url") or ""),
                })
            return results
        except Exception as exc:
            logger.error("structured_search falló: %s", exc)
            return []

    def _lookup_movie(self, title: str) -> dict | None:
        try:
            search_results = self._tmdb.search_movies(title)
            items = search_results.get("results", [])
            if not items:
                return None
            first = items[0]
            movie_id = first["id"]

            details = self._tmdb.get_movie_details(movie_id)
            credits = self._tmdb.get_movie_credits(movie_id)

            director = next(
                (p["name"] for p in credits.get("crew", []) if p.get("job") == "Director"),
                "",
            )
            cast_sorted = sorted(
                credits.get("cast", []), key=lambda p: p.get("order", 999)
            )
            cast_top3 = [p["name"] for p in cast_sorted[:3]]

            genres = [g["name"] for g in details.get("genres", [])]
            poster_path = details.get("poster_path")

            return {
                "id": str(movie_id),
                "title": str(details.get("title") or first.get("title") or ""),
                "year": (details.get("release_date") or "")[:4] or None,
                "director": director,
                "genres": ", ".join(genres),
                "overview": str(details.get("overview") or ""),
                "vote_average": _to_float(details.get("vote_average")),
                "runtime": _to_int(details.get("runtime")),
                "poster_url": (
                    self._tmdb.build_poster_url(poster_path) if poster_path else ""
                ),
                "cast_top3": cast_top3,
            }
        except Exception:
            logger.exception("Error en _lookup_movie para título '%s'", title)
            return None

    # ── API helper con retry ──────────────────────────────────────────────────

    def _generate_content_with_retry(
        self,
        contents: list,
        config: types.GenerateContentConfig,
        max_retries: int = 3,
    ):
        for attempt in range(max_retries):
            try:
                return self._genai_client.models.generate_content(
                    model=CHAT_MODEL,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                msg = str(exc)
                is_rate_limit = "429" in msg or "RESOURCE_EXHAUSTED" in msg
                if is_rate_limit and attempt < max_retries - 1:
                    wait = 10 * (2 ** attempt)  # 10 s, 20 s, 40 s
                    logger.warning(
                        "Rate limit (429), reintento %d/%d en %ds…",
                        attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                else:
                    raise

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def _execute_tool_call(self, function_call: Any) -> Any:
        name = function_call.name
        args = function_call.args or {}

        if name == "semantic_search":
            return self._semantic_search(
                query=str(args["query"]),
                n_results=int(args.get("n_results", 5)),
            )
        if name == "structured_search":
            return self._structured_search(dict(args))
        if name == "lookup_movie":
            result = self._lookup_movie(str(args["title"]))
            return [result] if result is not None else []

        logger.warning("Tool desconocida: '%s'", name)
        return []

    # ── Conversación ──────────────────────────────────────────────────────────

    def chat(self, user_message: str) -> dict:
        """Procesa un mensaje del usuario y retorna respuesta + recomendaciones.

        Returns:
            {"text": str, "recommendations": list[dict]}
        """
        self._history.append(
            types.Content(role="user", parts=[types.Part(text=user_message)])
        )

        config = types.GenerateContentConfig(
            system_instruction=self._system_instruction,
            tools=self._tools,
        )

        seen_ids: set[str] = set()
        last_tool_results: list[dict] = []
        final_response = None
        max_iterations = 5

        for _ in range(max_iterations):
            response = self._generate_content_with_retry(
                contents=self._history[-MAX_HISTORY_MESSAGES:],
                config=config,
            )

            if not response.function_calls:
                final_response = response
                if response.candidates and response.candidates[0].content:
                    self._history.append(response.candidates[0].content)
                break

            self._history.append(response.candidates[0].content)

            function_response_parts: list[types.Part] = []
            for fc in response.function_calls:
                raw_result = self._execute_tool_call(fc)

                if isinstance(raw_result, list):
                    for item in raw_result:
                        if isinstance(item, dict):
                            item_id = item.get("id")
                            if item_id and item_id not in seen_ids:
                                seen_ids.add(item_id)
                                last_tool_results.append(item)
                            elif not item_id:
                                last_tool_results.append(item)

                function_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": raw_result},
                    )
                )

            self._history.append(
                types.Content(role="user", parts=function_response_parts)
            )
        else:
            logger.warning("Loop alcanzó max_iterations=%d sin respuesta final", max_iterations)

        text = (final_response.text if final_response else "") or ""
        text = re.sub(r"```json[\s\S]*?```", "", text).strip()

        new_recs = [m for m in last_tool_results if m.get("id") not in self._shown_ids]
        self._shown_ids.update(m["id"] for m in new_recs if m.get("id"))

        return {
            "text": text,
            "recommendations": new_recs[:5],
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    assistant = CineMatchAssistant()
    for msg in [
        "Hola",
        "Recomiéndame algo parecido a Interstellar pero más corto",
    ]:
        result = assistant.chat(msg)
        print(f"\nUser: {msg}")
        print(f"Text: {result['text'][:300]}...")
        print(f"Recommendations: {len(result['recommendations'])}")
        print("---")
