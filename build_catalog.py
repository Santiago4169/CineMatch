"""Script para construir el catálogo de películas desde TMDB."""
import logging
import sys
from pathlib import Path

from src.catalog import CATALOG_FILENAME, CatalogBuilder
from src.config import DATA_DIR
from src.tmdb_client import TMDBClient, TMDBError


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("build_catalog")

    try:
        client = TMDBClient()
        builder = CatalogBuilder(client)
        builder.build()

        output_path = Path(DATA_DIR) / CATALOG_FILENAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        builder.save(output_path)

        logger.info("Catálogo guardado en %s", output_path)
        return 0

    except TMDBError as exc:
        logger.error("Error fatal de TMDB: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrumpido por el usuario.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
