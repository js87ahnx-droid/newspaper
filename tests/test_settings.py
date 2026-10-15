import shutil
from pathlib import Path

import pytest
import yaml

from pipeline.__main__ import main
from pipeline.settings import ROOT, SettingsError, load_config, load_interests, load_sources


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name in ("config.yaml", "sources.yaml", "interests.yaml"):
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


def edit(root: Path, name: str, fn) -> None:
    path = root / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_repo_settings_are_valid():
    load_config()
    load_sources()
    load_interests()
    assert main(["validate"]) == 0


@pytest.mark.parametrize(
    "name, mutate, expect",
    [
        ("config.yaml", lambda d: d["weights"].update(attention=-0.1), "weights.attention"),
        ("config.yaml", lambda d: d["weights"].update(attention=0, importance=0, continuity=0, interest=0), "가중치 합"),
        ("config.yaml", lambda d: d["editing"].update(diversity_ratio=0.6, interest_cap=0.5), "1을 넘음"),
        ("config.yaml", lambda d: d["editing"].update(interest_cap=1.5), "editing.interest_cap"),
        ("config.yaml", lambda d: d["window"].update(start="25:00"), "HH:MM"),
        ("config.yaml", lambda d: d.update(timezone="Mars/Base"), "알 수 없는 시간대"),
        ("config.yaml", lambda d: d["sections"].append(dict(d["sections"][1])), "섹션 id 중복"),
        ("config.yaml", lambda d: d["sections"].reverse(), "첫 섹션은 front"),
        ("config.yaml", lambda d: d["weights"].update(atention=0.1), "atention"),
        ("config.yaml", lambda d: d["llm"].update(max_issues_per_day=-1), "llm.max_issues_per_day"),
        ("sources.yaml", lambda d: d["sources"][0].update(enabled=True, feeds=[]), "feeds 가 비어"),
        ("sources.yaml", lambda d: d["sources"][0].update(weight=-1), "weight"),
        ("sources.yaml", lambda d: d["sources"][0].update(lean="극우"), "lean"),
        ("sources.yaml", lambda d: d["sources"][0].update(country="kor"), "country"),
        ("sources.yaml", lambda d: d["sources"].append(dict(d["sources"][0])), "매체명 중복"),
        ("sources.yaml", lambda d: d["sources"][0].update(enabled=True, feeds=[{"section": "top", "url": "ftp://x"}]), "url"),
        ("interests.yaml", lambda d: d["topics"].update(economy=-2), "음수"),
        ("interests.yaml", lambda d: d.update(foreign_title="both"), "foreign_title"),
    ],
)
def test_invalid_values_rejected(root, name, mutate, expect, capsys):
    edit(root, name, mutate)
    loader = {"config.yaml": load_config, "sources.yaml": load_sources, "interests.yaml": load_interests}[name]
    with pytest.raises(SettingsError) as e:
        loader(root)
    assert expect in str(e.value)
    assert name in str(e.value)
    # CLI 도 실패 코드와 함께 같은 이유를 출력
    assert main(["--root", str(root), "validate"]) == 1
    assert expect in capsys.readouterr().err


def test_yaml_syntax_error_reported(root):
    (root / "config.yaml").write_text("weights: [unclosed", encoding="utf-8")
    with pytest.raises(SettingsError, match="YAML 문법 오류"):
        load_config(root)


def test_missing_file_reported(root):
    (root / "interests.yaml").unlink()
    with pytest.raises(SettingsError, match="파일 없음"):
        load_interests(root)
