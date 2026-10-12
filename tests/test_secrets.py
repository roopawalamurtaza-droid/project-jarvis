import os

import pytest

from jarvis.secrets import SecretStore


@pytest.mark.skipif(os.name != "nt", reason="Current-user DPAPI requires Windows")
def test_dpapi_roundtrip_no_plaintext(tmp_path):
    store = SecretStore(tmp_path)
    secret = "jarvis-test-only-not-a-real-api-key"
    store.set("openai", secret)
    assert secret not in store.path.read_text()
    assert SecretStore(tmp_path).get("openai") == secret
    store.delete("openai")
    assert not store._read().get("openai")


def test_environment_fallback_and_invalid_name(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    store = SecretStore(tmp_path)
    assert store.get("gemini") == "test-key"
    with pytest.raises(ValueError):
        store.get("../secret")
