import pytest


@pytest.fixture(autouse=True)
def _empty_history(tmp_path, monkeypatch):
    """시간창이 직전 발행 기록(data/history)에 따라 달라지므로, 테스트는 저장소의 실제 기록 대신 빈 폴더를 쓴다."""
    import pipeline.prepare

    monkeypatch.setattr(pipeline.prepare, "DEFAULT_HISTORY", tmp_path / "_history")
