import re
import unicodedata

def normalize_term(term: str) -> str:
    """
    Normaliza un término para búsquedas y comparaciones uniformes:
    - Convierte a minúsculas.
    - Remueve acentos y diacríticos.
    - Reemplaza puntuación y caracteres especiales con espacios.
    - Contrae múltiples espacios en blanco.
    """
    if not term:
        return ""
    
    # Minúsculas
    term = term.lower()
    
    # Remover diacríticos
    term = "".join(
        c for c in unicodedata.normalize("NFD", term)
        if unicodedata.category(c) != "Mn"
    )
    
    # Reemplazar puntuación con espacios
    term = re.sub(r"[^\w\s]", " ", term)
    
    # Espacios limpios
    term = " ".join(term.split())
    
    return term
