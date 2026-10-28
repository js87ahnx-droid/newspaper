import pytest


@pytest.fixture(autouse=True)
def _empty_history(tmp_path, monkeypatch):
    """시간창이 직전 발행 기록(data/history)에 따라 달라지므로, 테스트는 저장소의 실제 기록 대신 빈 폴더를 쓴다."""
    import pipeline.prepare

    monkeypatch.setattr(pipeline.prepare, "DEFAULT_HISTORY", tmp_path / "_history")


@pytest.fixture(autouse=True)
def _no_real_learned(tmp_path, monkeypatch):
    """편집 결과가 주간 관심 학습값(data/interests-learned.json, S30b — 발행이 커밋)에 따라 달라지므로, 저장소 루트에서 읽을 때는
    없는 파일을 가리킨다. 임시 폴더를 루트로 쓰는 학습값 테스트(test_learned)는 그대로."""
    from pathlib import Path

    from pipeline import learned
    from pipeline.settings import ROOT

    orig = learned.learned_path
    monkeypatch.setattr(learned, "learned_path",
                        lambda root: tmp_path / "_learned.json" if Path(root).resolve() == Path(ROOT).resolve() else orig(root))
