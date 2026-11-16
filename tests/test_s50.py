"""S50 큐레이션 판: 설정·변환·두 판 발행."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.settings import Curated, load_config


# ---------- S50a 설정 ----------
def test_curated_config_loads():
    c = load_config().curated
    assert c.enabled and c.keep["politics"] == 4 and c.list_max == 6
    cfg = load_config()
    assert sum(c.pages.get(s.id, s.pages) for s in cfg.sections) <= 24


@pytest.mark.parametrize("bad", [
    {"keep": {"front": 3}},          # 1면은 줄이지 않음
    {"keep": {"briefs": 3}},
    {"keep": {"politics": 0}},       # 면 머리는 늘 남김
    {"pages": {"politics": -1}},
    {"list_max": 30},
    {"keep": {"nowhere": 3}},
])
def test_curated_config_rejects(bad):
    with pytest.raises(ValidationError):
        Curated(**bad)
