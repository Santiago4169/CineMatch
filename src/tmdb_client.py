"""Cliente HTTP para la API de TMDB (The Movie Database) — CineMatch."""

import logging
import time
from typing import Optional

import requests

from src.config import TMDB_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
DEFAULT_LANGUAGE = "es-ES"
DEFAULT_REGION = "CO"
MIN_REQUEST_INTERVAL = 0.05  # 50 ms → ~20 req/s conservador


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

class TMDBError(Exception):
    """Error base para fallos en la API de TMDB."""


class TMDBAuthError(TMDBError):
    """API key inválida o expirada (HTTP 401)."""


class TMDBNotFoundError(TMDBError):
    """Recurso no encontrado en TMDB (HTTP 404)."""


class TMDBRateLimitError(TMDBError):
    """Demasiadas peticiones a la API (HTTP 429)."""


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class TMDBClient:
    """Cliente para la API v3 de TMDB con autenticación Bearer.

    Gestiona rate limiting, parámetros de idioma/región y conversión de
    errores HTTP en excepciones tipadas.

    Args:
        api_key: Token de acceso Bearer. Si es None, usa config.TMDB_API_KEY.
        language: Código de idioma BCP-47 (por defecto "es-ES").
        region: Código ISO 3166-1 de región (por defecto "CO").

    Raises:
        ValueError: Si api_key está vacía.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
        region: str = DEFAULT_REGION,
    ) -> None:
        resolved_key = api_key or TMDB_API_KEY
        if not resolved_key:
            raise ValueError("api_key no puede estar vacía.")

        self.language = language
        self.region = region
        self._last_request_time: float = 0.0

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {resolved_key}",
            "accept": "application/json",
        })

    # -----------------------------------------------------------------------
    # Métodos privados
    # -----------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    def _request(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Realiza un GET autenticado a la API de TMDB.

        Args:
            endpoint: Ruta relativa, p. ej. "/movie/popular".
            params: Parámetros de consulta adicionales.

        Returns:
            Respuesta JSON deserializada como dict.

        Raises:
            TMDBAuthError: Clave inválida o expirada.
            TMDBNotFoundError: El recurso solicitado no existe.
            TMDBRateLimitError: Se superó el límite de peticiones.
            TMDBError: Cualquier otro error HTTP o de red.
        """
        self._wait_for_rate_limit()

        url = f"{BASE_URL}{endpoint}"
        merged_params = {"language": self.language, "region": self.region}
        if params:
            merged_params.update(params)

        logger.debug("GET %s params=%s", url, merged_params)

        try:
            response = self.session.get(url, params=merged_params, timeout=10)
        except requests.exceptions.RequestException as exc:
            raise TMDBError(f"Error de red al contactar TMDB: {exc}") from exc

        if response.ok:
            return response.json()

        code = response.status_code
        if code == 401:
            raise TMDBAuthError("API key inválida o expirada.")
        if code == 404:
            raise TMDBNotFoundError(f"Recurso no encontrado: {endpoint}")
        if code == 429:
            raise TMDBRateLimitError("Demasiadas peticiones, espera un momento.")

        raise TMDBError(f"Error HTTP {code} al llamar {endpoint}: {response.text[:200]}")

    # -----------------------------------------------------------------------
    # Métodos públicos — películas
    # -----------------------------------------------------------------------

    def get_movie_details(self, movie_id: int) -> dict:
        """Retorna los detalles completos de una película.

        Args:
            movie_id: Identificador numérico de TMDB.

        Returns:
            Dict con título, sinopsis, géneros, popularidad, etc.

        Raises:
            TMDBNotFoundError: Si el ID no corresponde a ninguna película.
            TMDBError: Ante cualquier otro fallo de red o API.

        Example:
            >>> cliente = TMDBClient()
            >>> pelicula = cliente.get_movie_details(157336)
            >>> print(pelicula["title"])  # "Interstellar"
        """
        return self._request(f"/movie/{movie_id}")

    def search_movies(self, query: str, page: int = 1) -> dict:
        """Busca películas por texto libre.

        Args:
            query: Término de búsqueda (título, actor, etc.).
            page: Número de página (1-indexed).

        Returns:
            Dict con claves "results" (lista de películas) y "total_pages".

        Raises:
            TMDBError: Ante cualquier fallo de red o API.
        """
        return self._request("/search/movie", {
            "query": query,
            "page": page,
            "include_adult": False,
        })

    def get_popular_movies(self, page: int = 1) -> dict:
        """Retorna el listado de películas más populares en este momento.

        Args:
            page: Número de página (1-indexed).

        Returns:
            Dict con "results" y "total_pages".

        Raises:
            TMDBError: Ante cualquier fallo de red o API.
        """
        return self._request("/movie/popular", {"page": page})

    def get_top_rated_movies(self, page: int = 1) -> dict:
        """Retorna el listado de películas mejor valoradas.

        Usado en la Fase 2 para construir el catálogo base del asistente.

        Args:
            page: Número de página (1-indexed).

        Returns:
            Dict con "results" y "total_pages".

        Raises:
            TMDBError: Ante cualquier fallo de red o API.
        """
        return self._request("/movie/top_rated", {"page": page})

    def discover_movies(self, page: int = 1, **filters) -> dict:
        """Descubre películas aplicando filtros estructurados.

        Es el método más flexible del cliente. Acepta cualquier parámetro
        soportado por el endpoint /discover/movie de TMDB.

        Args:
            page: Número de página (1-indexed).
            **filters: Filtros adicionales, por ejemplo:
                - with_genres="28,12"  (IDs de género separados por coma)
                - primary_release_year=2023
                - vote_average.gte=7.5
                - sort_by="vote_average.desc"

        Returns:
            Dict con "results" y "total_pages".

        Raises:
            TMDBError: Ante cualquier fallo de red o API.

        Example:
            >>> cliente = TMDBClient()
            >>> accion = cliente.discover_movies(
            ...     with_genres="28", sort_by="popularity.desc"
            ... )
        """
        params = {"page": page, **filters}
        return self._request("/discover/movie", params)

    # -----------------------------------------------------------------------
    # Métodos públicos — metadatos
    # -----------------------------------------------------------------------

    def get_genres(self) -> list[dict]:
        """Retorna la lista de géneros cinematográficos disponibles en TMDB.

        Returns:
            Lista de dicts con "id" (int) y "name" (str), en el idioma
            configurado en el cliente.

        Raises:
            TMDBError: Ante cualquier fallo de red o API.

        Example:
            >>> cliente = TMDBClient()
            >>> generos = cliente.get_genres()
            >>> print(generos[0])  # {"id": 28, "name": "Acción"}
        """
        data = self._request("/genre/movie/list")
        return data.get("genres", [])

    def get_movie_credits(self, movie_id: int) -> dict:
        """Retorna el reparto y equipo técnico de una película.

        Args:
            movie_id: Identificador numérico de TMDB.

        Returns:
            Dict con "cast" (lista de actores) y "crew" (lista de equipo).
            Cada actor incluye "name", "character" y "order".
            Cada miembro del equipo incluye "name" y "job".

        Raises:
            TMDBNotFoundError: Si el ID no corresponde a ninguna película.
            TMDBError: Ante cualquier otro fallo de red o API.

        Example:
            >>> cliente = TMDBClient()
            >>> creditos = cliente.get_movie_credits(157336)
            >>> director = next(
            ...     p for p in creditos["crew"] if p["job"] == "Director"
            ... )
            >>> print(director["name"])  # "Christopher Nolan"
        """
        return self._request(f"/movie/{movie_id}/credits")

    def get_movie_keywords(self, movie_id: int) -> list[str]:
        """Retorna las palabras clave asociadas a una película.

        Args:
            movie_id: Identificador numérico de TMDB.

        Returns:
            Lista de strings con los nombres de las keywords.

        Raises:
            TMDBNotFoundError: Si el ID no corresponde a ninguna película.
            TMDBError: Ante cualquier otro fallo de red o API.
        """
        data = self._request(f"/movie/{movie_id}/keywords")
        return [kw["name"] for kw in data.get("keywords", [])]

    # -----------------------------------------------------------------------
    # Utilidades
    # -----------------------------------------------------------------------

    def build_poster_url(self, poster_path: Optional[str], size: str = "w500") -> Optional[str]:
        """Construye la URL completa de un póster desde su ruta relativa.

        Args:
            poster_path: Ruta relativa devuelta por TMDB (p. ej. "/abc123.jpg").
                Si es None o vacía, retorna None.
            size: Tamaño de imagen. Valores válidos:
                w92, w154, w185, w342, w500, w780, original.

        Returns:
            URL completa de la imagen, o None si poster_path no es válida.

        Example:
            >>> cliente = TMDBClient()
            >>> url = cliente.build_poster_url("/qJ2tW6WMUDux911r6m7haRef0WH.jpg")
            >>> print(url)
            'https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg'
        """
        if not poster_path:
            return None
        return f"{IMAGE_BASE_URL}/{size}{poster_path}"


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.WARNING)

    try:
        cliente = TMDBClient()
        pelicula = cliente.get_movie_details(157336)  # Interstellar
        print(f"Título   : {pelicula['title']}")
        print(f"Sinopsis : {pelicula.get('overview', '(sin sinopsis)')[:120]}...")
        print("OK — conexión con TMDB verificada.")
    except TMDBError as exc:
        print(f"[{type(exc).__name__}] {exc}", file=sys.stderr)
        sys.exit(1)
