def extract_listener_block(content: str, marker: str) -> str:
    """Extrae el bloque del callback de un listener o función de forma lineal O(N) sin regex."""
    start_idx = content.find(marker)
    if start_idx == -1:
        raise ValueError(f"Marcador '{marker}' no encontrado")

    brace_start = content.find("{", start_idx)
    if brace_start == -1:
        raise ValueError(f"Llave de apertura no encontrada después de '{marker}'")

    depth = 0
    end_idx = -1
    for i in range(brace_start, len(content)):
        char = content[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break

    if end_idx == -1:
        raise ValueError(f"Llave de cierre no encontrada para '{marker}'")

    return content[brace_start:end_idx]


def test_corr_ui_01_me_interesa_listener_behavior():
    """CORR-UI-01 — El listener del botón 'Me interesa' invoca sendFeedback con 'more_like_this'."""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()

    marker = 'card.querySelector(".btn-more").addEventListener'
    block_code = extract_listener_block(content, marker)

    # Verificar que invoca 'more_like_this' y no 'accept_channel'
    assert 'sendFeedback(video.id, "more_like_this", null, catId)' in block_code
    assert "accept_channel" not in block_code


def test_corr_ui_03_feedback_error_handling_app_js():
    """CORR-UI-03 — sendFeedback valida response.ok, lanza error, y los listeners evitan remover la tarjeta."""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Verificar definición de sendFeedback
    marker_send = "async function sendFeedback("
    send_feedback_block = extract_listener_block(content, marker_send)

    assert "!response.ok" in send_feedback_block
    assert "throw new Error" in send_feedback_block

    # 2. Verificar que cada listener estructurado ejecuta try -> sendFeedback -> card.remove() -> catch -> alert
    markers = [
        'card.querySelector(".btn-more").addEventListener',
        'card.querySelector(".btn-less").addEventListener',
        'card.querySelector(".btn-accept").addEventListener',
        'card.querySelector(".btn-hide").addEventListener',
        'card.querySelector(".btn-block-channel").addEventListener',
    ]

    for marker in markers:
        block = extract_listener_block(content, marker)
        pos_try = block.find("try")
        pos_send = block.find("sendFeedback")
        pos_remove = block.find("card.remove()")
        pos_catch = block.find("catch")
        pos_alert = block.find("showAlertDialog")

        assert pos_try != -1, f"Missing 'try' in {marker}"
        assert pos_send != -1, f"Missing 'sendFeedback' in {marker}"
        assert pos_remove != -1, f"Missing 'card.remove()' in {marker}"
        assert pos_catch != -1, f"Missing 'catch' in {marker}"
        assert pos_alert != -1, f"Missing 'showAlertDialog' in {marker}"

        assert pos_try < pos_send < pos_remove < pos_catch < pos_alert, (
            f"Orden incorrecto en {marker}: try ({pos_try}) < sendFeedback ({pos_send}) "
            f"< card.remove() ({pos_remove}) < catch ({pos_catch}) < showAlertDialog ({pos_alert})"
        )
