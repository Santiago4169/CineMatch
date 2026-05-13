import chromadb
import google.generativeai as genai
from src.config import GEMINI_API_KEY

genai.configure(api_key=GEMINI_API_KEY)

client = chromadb.PersistentClient(path='data/chroma_db')
col = client.get_collection('cinematch_movies')

print(f'Total indexadas: {col.count()}')

query = 'ciencia ficción contemplativa sobre el espacio y la soledad'

result = genai.embed_content(
    model='models/gemini-embedding-2',
    content=query,
    task_type='retrieval_query'
)

vec = result['embedding']

res = col.query(
    query_embeddings=[vec],
    n_results=5
)

print(f'\nResultados para query: {query!r}')

for i in range(len(res['ids'][0])):
    title = res['metadatas'][0][i]['title']
    genres = res['metadatas'][0][i]['genres']
    distance = res['distances'][0][i]

    print(f'{i+1}. {title} ({genres}) - dist: {distance:.3f}')
