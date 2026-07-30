from cryptography.fernet import Fernet
from flask import current_app


def _get_fernet():
    """Inicializa la instancia de Fernet usando la clave configurada."""
    key = current_app.config["TOKEN_ENCRYPTION_KEY"]
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)

def encrypt_token(token: str) -> str:
    """Cifra un token de texto plano a una cadena cifrada en base64."""
    if not token:
        return ""
    f = _get_fernet()
    return f.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Descifra una cadena cifrada en base64 de vuelta a texto plano."""
    if not encrypted_token:
        return ""
    f = _get_fernet()
    return f.decrypt(encrypted_token.encode()).decode()
