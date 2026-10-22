"""Local-only configuration applied before importing Mnemosyne."""
import os
from pathlib import Path

ROOT = Path(os.environ.get('PERSONAL_ARCHIVE_HOME', Path(__file__).resolve().parent)).resolve()
DATA_DIR = ROOT / 'data'
MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
os.environ['MNEMOSYNE_DATA_DIR'] = str(DATA_DIR)
os.environ['MNEMOSYNE_FASTEMBED_CACHE_DIR'] = str(Path(__file__).resolve().parent / 'models')
os.environ['MNEMOSYNE_EMBEDDING_MODEL'] = MODEL
os.environ['MNEMOSYNE_EMBEDDING_DIM'] = '384'
os.environ['MNEMOSYNE_EMBEDDING_THREADS'] = '2'
os.environ['MNEMOSYNE_EMBEDDINGS_VIA_API'] = '0'
os.environ.pop('MNEMOSYNE_EMBEDDING_API_URL', None)
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'

