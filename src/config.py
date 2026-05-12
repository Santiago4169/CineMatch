from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
TMDB_API_KEY: str = os.getenv("TMDB_API_KEY", "")

_missing = [name for name, val in (
    ("GEMINI_API_KEY", GEMINI_API_KEY),
    ("TMDB_API_KEY", TMDB_API_KEY),
) if not val]

if _missing:
    raise EnvironmentError(
        f"Faltan variables de entorno requeridas: {', '.join(_missing)}. "
        "Copia .env.example como .env y rellena las claves."
    )

CHROMA_DB_PATH: str = "chroma_db"
DATA_DIR: str = "data"
