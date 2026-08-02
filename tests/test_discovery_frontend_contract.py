import re
import pytest

def test_corr_ui_01_me_interesa_sends_more_like_this():
    """CORR-UI-01 — El botón 'Me interesa' debe enviar la acción 'more_like_this'."""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()

    # Verify Me interesa HTML button uses btn-more
    assert 'btn-more' in content
    
    # Verify the listener for btn-more calls sendFeedback with 'more_like_this'
    match = re.search(r'\.btn-more.*?\.addEventListener.*?more_like_this', content, re.DOTALL)
    assert match is not None, "btn-more should add listener calling more_like_this"


def test_corr_ui_03_error_keeps_card_and_notifies():
    """CORR-UI-03 — Si la llamada de feedback falla, la tarjeta no se remueve del DOM."""
    with open("app/static/js/app.js", "r", encoding="utf-8") as f:
        content = f.read()

    # Verify that in sendFeedback, we check !response.ok and throw an error
    assert "!response.ok" in content
    assert "throw new Error" in content

    # Verify that action listeners use try/catch blocks where card.remove() is inside the try block
    # and showAlertDialog is in the catch block (preventing removal on error)
    matches = re.findall(r'try\s*\{\s*await\s+sendFeedback.*?\s+card\.remove\(\);\s*\}\s*catch', content, re.DOTALL)
    assert len(matches) >= 4, f"Feedback listener blocks should catch errors before card.remove(), found only {len(matches)} matches"
