import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.auth.encryption import encrypt_token
from app.db import get_db

auth_bp = Blueprint("auth", __name__)

def get_utc_now_iso():
    """Retorna la fecha y hora UTC actual en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()

def save_credentials(access_token, refresh_token, expires_in):
    """Guarda o actualiza las credenciales cifradas en la base de datos."""
    db = get_db()
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(seconds=expires_in)).isoformat()
    now_iso = now.isoformat()

    enc_access = encrypt_token(access_token)
    enc_refresh = encrypt_token(refresh_token) if refresh_token else None

    # Comprobar si ya existe una credencial
    cursor = db.execute("SELECT id, refresh_token FROM credentials LIMIT 1")
    row = cursor.fetchone()

    if row:
        # Si ya existe, actualizamos. Si no se recibió un nuevo refresh_token, conservamos el anterior.
        if enc_refresh:
            db.execute("""
                UPDATE credentials
                SET access_token = ?, refresh_token = ?, expires_at = ?, updated_at = ?
                WHERE id = ?
            """, (enc_access, enc_refresh, expires_at, now_iso, row["id"]))
        else:
            db.execute("""
                UPDATE credentials
                SET access_token = ?, expires_at = ?, updated_at = ?
                WHERE id = ?
            """, (enc_access, expires_at, now_iso, row["id"]))
    else:
        # Si no existe, creamos una nueva fila
        db.execute("""
            INSERT INTO credentials (access_token, refresh_token, expires_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (enc_access, enc_refresh, expires_at or "", now_iso))

    db.commit()

@auth_bp.route("/auth/login", methods=["GET"])
def login():
    """Redirige al usuario al flujo de autorización de Google."""
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    params = {
        "client_id": current_app.config["GOOGLE_CLIENT_ID"],
        "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid email https://www.googleapis.com/auth/youtube.readonly",
        "state": state,
        "access_type": "offline",
        "prompt": "consent"
    }

    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(google_auth_url)

@auth_bp.route("/auth/callback", methods=["GET"])
def callback():
    """Procesa el retorno de Google OAuth 2.0 y valida el propietario."""
    state = request.args.get("state")
    code = request.args.get("code")
    error = request.args.get("error")

    if error:
        return jsonify({"error": {"code": "AUTH_ERROR", "message": f"Error de autorización: {error}"}}), 400

    # Validar el state para prevenir ataques CSRF en OAuth
    session_state = session.get("oauth_state")
    if not state or not session_state or state != session_state:
        return jsonify({"error": {"code": "INVALID_STATE", "message": "Estado de sesión inválido o expirado."}}), 400

    # Limpiar el state de la sesión de inmediato
    session.pop("oauth_state", None)

    if not code:
        return jsonify({"error": {"code": "MISSING_CODE", "message": "Código de autorización faltante."}}), 400

    # Intercambiar código por tokens
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": current_app.config["GOOGLE_CLIENT_ID"],
        "client_secret": current_app.config["GOOGLE_CLIENT_SECRET"],
        "redirect_uri": current_app.config["GOOGLE_REDIRECT_URI"],
        "grant_type": "authorization_code"
    }

    try:
        response = requests.post(token_url, data=token_data, timeout=10)
        if response.status_code != 200:
            return jsonify({
                "error": {
                    "code": "TOKEN_EXCHANGE_FAILED",
                    "message": "Fallo al intercambiar el código de autorización.",
                    "details": response.json()
                }
            }), 400

        tokens = response.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)

        # Obtener información del usuario para verificar el email
        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        userinfo_resp = requests.get(userinfo_url, headers=headers, timeout=10)

        if userinfo_resp.status_code != 200:
            return jsonify({
                "error": {
                    "code": "USERINFO_FAILED",
                    "message": "No se pudo obtener la información de usuario de Google."
                }
            }), 400

        user_data = userinfo_resp.json()
        email = user_data.get("email")

        # Restricción estricta al propietario configurado
        owner_email = current_app.config["OWNER_GOOGLE_EMAIL"]
        if not email or email.lower() != owner_email.lower():
            # Destruir cualquier sesión por seguridad
            session.clear()
            return jsonify({
                "error": {
                    "code": "ACCESS_DENIED",
                    "message": "Acceso denegado: este correo no corresponde al propietario configurado."
                }
            }), 403

        # Guardar credenciales de manera persistente y cifrada
        save_credentials(access_token, refresh_token, expires_in)

        # Iniciar sesión segura, rotando el ID de sesión
        session.clear()
        session["authenticated"] = True
        session["email"] = email
        session["csrf_token"] = secrets.token_hex(32)

        return redirect("/")

    except Exception as e:
        return jsonify({
            "error": {
                "code": "SERVER_ERROR",
                "message": f"Error interno durante la autenticación: {e}"
            }
        }), 500

@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    """Invalida la sesión actual del usuario."""
    # Nota: CSRF se validará a nivel de before_request en la app
    session.clear()
    return "", 204

@auth_bp.route("/auth/status", methods=["GET"])
def auth_status():
    """Retorna el estado de autenticación y el token CSRF activo."""
    authenticated = session.get("authenticated", False)
    email = session.get("email") if authenticated else None

    # Generar un token CSRF si no existe en la sesión
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)

    csrf_token = session["csrf_token"]

    return jsonify({
        "authenticated": authenticated,
        "email": email,
        "csrfToken": csrf_token
    }), 200
