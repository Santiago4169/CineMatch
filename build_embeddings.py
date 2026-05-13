"""Script para construir los embeddings semánticos del catálogo — CineMatch Fase 3."""
import argparse
import logging
import sys
from pathlib import Path

from src.config import DATA_DIR
from src.embeddings import CATALOG_FILENAME, EmbeddingsBuilder, EmbeddingsError


def main() -> int:
    parser = argparse.ArgumentParser(description="Construye embeddings del catálogo CineMatch.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra los embeddings existentes y empieza de cero.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="No retomar desde IDs existentes (reprocesa todo el catálogo).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("build_embeddings")

    try:
        builder = EmbeddingsBuilder()

        if args.reset:
            logger.warning("Reseteando colección de ChromaDB (se perderán los embeddings actuales)…")
            builder.reset_collection()

        catalog_path = Path(DATA_DIR) / CATALOG_FILENAME
        stats = builder.build(catalog_path=catalog_path, resume=not args.no_resume)

        logger.info("=== Construcción completada ===")
        logger.info("Stats: %s", stats)
        return 0

    except FileNotFoundError as exc:
        logger.error("Catálogo no encontrado: %s. Ejecuta build_catalog.py primero.", exc)
        return 1
    except EmbeddingsError as exc:
        logger.error("Error fatal: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrumpido. El progreso parcial se conservó en ChromaDB.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
