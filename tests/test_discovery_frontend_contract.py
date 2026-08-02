import re


def test_corr_ui_01_me_interesa_listener_behavior():
    """CORR-UI-01 — El listener del botón 'Me interesa' invoca sendFeedback con 'more_like_this'."""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()

    # Buscar el bloque del event listener para .btn-more
    match = re.search(
        r'\.btn-more"\)\.addEventListener\("click",\s*async\s*\(\)\s*=>\s*\{([^{}]*(\{([^{}]*)*\})*[^{}]*)\}\)',
        content,
    )
    assert match is not None, "No se encontró el listener de click para .btn-more"

    block_code = match.group(0)

    # Verificar que invoca 'more_like_this' y no 'accept_channel'
    assert 'sendFeedback(video.id, "more_like_this", null, catId)' in block_code
    assert 'accept_channel' not in block_code


def test_corr_ui_03_feedback_error_handling_app_js():
    """CORR-UI-03 — sendFeedback valida response.ok, lanza error, y los listeners evitan remover la tarjeta."""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Verificar definición de sendFeedback
    assert "async function sendFeedback" in content
    # Buscar el cuerpo de sendFeedback
    send_feedback_match = re.search(r"async function sendFeedback\(.*?\}\s*\}\s*\}", content, re.DOTALL)
    assert send_feedback_match is not None, "No se encontró la función sendFeedback en app.js"
    send_feedback_body = send_feedback_match.group(0)

    # Verificar que maneja !response.ok y propaga el error lanzando una excepción
    assert "!response.ok" in send_feedback_body
    assert "throw new Error" in send_feedback_body

    # 2. Verificar que cada listener de botón captura errores en try-catch y remueve la tarjeta en try
    btn_selectors = [".btn-more", ".btn-less", ".btn-accept", ".btn-hide", ".btn-block-channel"]
    for sel in btn_selectors:
        pattern = (
            rf'querySelector\("{sel}"\)\.addEventListener\("click",\s*async\s*\(\)\s*=>\s*\{{.*?try\s*\{{(.*?)\}}\s*catch'
        )
        match = re.search(pattern, content, re.DOTALL)
        assert match is not None, f"El listener para {sel} debe estructurarse con try/catch"
        try_body = match.group(1)
        # card.remove() debe estar dentro del bloque try
        assert "card.remove()" in try_body
