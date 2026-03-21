from glamtool.config import load_settings


def test_load_settings_reads_process_environment(monkeypatch):
    monkeypatch.setenv("GHOST_URL", "https://example.com")
    monkeypatch.setenv("GHOST_CONTENT_KEY", "secret-key")

    settings = load_settings()

    assert settings.ghost_url == "https://example.com"
    assert settings.ghost_content_key == "secret-key"


def test_load_settings_reads_explicit_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GHOST_URL", raising=False)
    monkeypatch.delenv("GHOST_CONTENT_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'GHOST_URL="https://ghost.example"\nGHOST_CONTENT_KEY="file-key"\n',
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.ghost_url == "https://ghost.example"
    assert settings.ghost_content_key == "file-key"
