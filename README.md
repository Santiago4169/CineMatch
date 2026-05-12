# 🎬 CineMatch

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-FF4B4B?logo=streamlit&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini_API-Flash-4285F4?logo=google&logoColor=white)
![TMDB](https://img.shields.io/badge/TMDB_API-v4-01D277?logo=themoviedatabase&logoColor=white)

**CineMatch** es un asistente conversacional en español que recomienda películas
combinando la inteligencia de Gemini Flash con búsqueda semántica vectorial sobre
el catálogo real de The Movie Database (TMDB).

Habla con él como hablarías con un amigo cinéfilo: cuéntale tu estado de ánimo,
con quién vas a ver la película o qué tienes ganas de sentir, y él te encontrará
opciones reales que encajen.

---

## Características

- **Conversacional** — mantiene el hilo de la conversación y recuerda tus preferencias
- **Semántico** — entiende peticiones por emoción o vibe, no solo por género o título
- **Datos reales** — todas las recomendaciones provienen del catálogo de TMDB
- **Sin inventos** — nunca sugiere películas que no existan en el catálogo
- **En español** — diseñado para usuarios de habla hispana (Colombia / neutro)
- **Local** — la base vectorial corre en tu máquina con ChromaDB, sin costos de nube

---

## Stack técnico

| Componente          | Tecnología                                  |
|---------------------|---------------------------------------------|
| Interfaz            | Streamlit                                   |
| LLM                 | Gemini Flash (google-generativeai)          |
| Embeddings          | text-embedding-004 (Google)                 |
| Base vectorial      | ChromaDB (local)                            |
| Datos de películas  | TMDB API v4                                 |
| Entorno             | Python 3.12, python-dotenv, pandas          |

---

## Instalación

### 1. Clona el repositorio

```bash
git clone https://github.com/tu-usuario/cinematch.git
cd cinematch
```

### 2. Crea y activa un entorno virtual

**Windows (PowerShell/CMD):**
```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Instala las dependencias

```bash
pip install -r requirements.txt
```

---

## Configuración de API keys

Copia el archivo de ejemplo y rellena con tus claves reales:

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

```bat
# Windows (CMD)
copy .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

Edita `.env`:

```env
GEMINI_API_KEY=tu_clave_de_gemini_aqui
TMDB_API_KEY=tu_clave_de_tmdb_aqui
```

### Dónde obtener las claves

| Servicio | URL                                                      |
|----------|----------------------------------------------------------|
| Gemini   | https://aistudio.google.com/app/apikey                   |
| TMDB     | https://www.themoviedb.org/settings/api                  |

> El archivo `.env` está en `.gitignore` — nunca se sube al repositorio.

---

## Uso

```bash
streamlit run app.py
```

Abre tu navegador en `http://localhost:8501` y empieza a chatear.

---

## Estructura del proyecto

```
cinematch/
├── .env.example          # Plantilla de variables de entorno
├── .gitignore
├── README.md
├── requirements.txt
├── app.py                # Entry point de Streamlit
├── prompts/
│   ├── personality.md    # Personalidad del asistente (tono y estilo)
│   └── system_prompt.md  # Instrucciones técnicas para el LLM
├── src/
│   ├── __init__.py
│   ├── config.py         # Carga de variables de entorno y constantes
│   ├── tmdb_client.py    # Cliente HTTP para TMDB API
│   ├── catalog.py        # Descarga y procesamiento del catálogo
│   ├── embeddings.py     # Generación de embeddings e indexado en ChromaDB
│   └── assistant.py      # Asistente conversacional con RAG
└── data/
    └── .gitkeep          # Carpeta para el catálogo descargado (no versionada)
```

---

## Roadmap de fases

| Fase | Descripción                                              | Estado  |
|------|----------------------------------------------------------|---------|
| 0    | Setup inicial — estructura, config, prompts              | Listo |
| 1    | Interfaz conversacional básica con Streamlit             | Pendiente |
| 2    | Integración con TMDB y descarga del catálogo             | Pendiente |
| 3    | Embeddings semánticos e indexado en ChromaDB             | Pendiente |
| 4    | Asistente completo con RAG y memoria conversacional      | Pendiente |
| 5    | Pulido, filtros avanzados y despliegue                   | Pendiente |

---

## Licencia

Este proyecto se desarrolla con fines académicos como parte del curso de
Ingenieria de Software en la Universidad de Pamplona (Colombia). El código es
libre para uso educativo y de aprendizaje.

Las marcas y datos de TMDB son propiedad de The Movie Database y se usan
bajo los términos de su API pública.

---

## Autor

Hecho con curiosidad y café por **Santiago De Avila Quintero**.

Si encuentras un bug o tienes una idea, abre un issue.
