from pathlib import Path
import tomllib


ROOT = Path(__file__).parents[1]


def test_runtime_dependency_files_keep_tokenizer_compatibility_constraints_in_sync():
    requirements = {
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = set(project["project"]["dependencies"])

    for constraint in {"transformers<5", "protobuf>=4.25"}:
        assert constraint in requirements
        assert constraint in dependencies
