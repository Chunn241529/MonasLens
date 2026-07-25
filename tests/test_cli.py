import json
from pathlib import Path

from typer.testing import CliRunner

from monas_lens.cli import app

runner = CliRunner()


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "monas-lens 0.1.0.dev0"


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app)

    assert result.exit_code == 0
    assert "Local-first repository intelligence" in result.stdout


def test_initialize_and_register_repository(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    repository = tmp_path / "repository"
    repository.mkdir()
    environment = {"MONAS_LENS_DATA_DIR": str(state_dir)}

    initialized = runner.invoke(app, ["init", "--json"], env=environment)
    added = runner.invoke(
        app,
        ["repo", "add", str(repository), "--json"],
        env=environment,
    )
    listed = runner.invoke(app, ["repo", "list", "--json"], env=environment)
    status = runner.invoke(app, ["repo", "status", "--json"], env=environment)

    assert initialized.exit_code == 0
    assert json.loads(initialized.stdout)["status"] == "initialized"
    assert added.exit_code == 0
    repository_id = json.loads(added.stdout)["id"]
    assert repository_id
    assert listed.exit_code == 0
    assert len(json.loads(listed.stdout)["repositories"]) == 1
    assert status.exit_code == 0
    assert json.loads(status.stdout)["id"] == repository_id


def test_repository_command_requires_initialization(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["repo", "list", "--json"],
        env={"MONAS_LENS_DATA_DIR": str(tmp_path / "missing")},
    )

    assert result.exit_code == 5
    assert json.loads(result.stderr)["error"]["code"] == "database_not_initialized"


def test_doctor_returns_not_ready_before_initialization(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["doctor", "--json"],
        env={"MONAS_LENS_DATA_DIR": str(tmp_path / "missing")},
    )

    assert result.exit_code == 5
    assert json.loads(result.stdout)["status"] == "not_ready"


def test_index_build_and_status_commands(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def run(value: int) -> str:\n    return str(value)\n",
        encoding="utf-8",
    )
    environment = {"MONAS_LENS_DATA_DIR": str(state_dir)}

    assert runner.invoke(app, ["init"], env=environment).exit_code == 0
    assert runner.invoke(app, ["repo", "add", str(repository)], env=environment).exit_code == 0
    built = runner.invoke(app, ["index", "build", "--json"], env=environment)
    status = runner.invoke(app, ["index", "status", "--json"], env=environment)

    assert built.exit_code == 0
    assert json.loads(built.stdout)["parsed_files"] == 1
    assert status.exit_code == 0
    status_payload = json.loads(status.stdout)
    assert status_payload["files"] == 1
    assert status_payload["symbols"] == 1


def test_search_command_returns_ranked_json_results(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def normalize_value(raw_input: str) -> str:\n    return raw_input.strip().lower()\n",
        encoding="utf-8",
    )
    environment = {"MONAS_LENS_DATA_DIR": str(state_dir)}

    assert runner.invoke(app, ["init"], env=environment).exit_code == 0
    assert runner.invoke(app, ["repo", "add", str(repository)], env=environment).exit_code == 0
    assert runner.invoke(app, ["index", "build"], env=environment).exit_code == 0

    result = runner.invoke(
        app,
        ["search", "normalize_value", "--limit", "5", "--json"],
        env=environment,
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["query"] == "normalize_value"
    assert payload["total"] > 0
    assert payload["results"][0]["qualified_name"] == "normalize_value"
    assert payload["results"][0]["match_type"] == "exact"


def test_graph_commands_return_filtered_json_results(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def helper() -> str:\n    return 'ok'\n\ndef run() -> str:\n    return helper()\n",
        encoding="utf-8",
    )
    environment = {"MONAS_LENS_DATA_DIR": str(state_dir)}

    assert runner.invoke(app, ["init"], env=environment).exit_code == 0
    assert runner.invoke(app, ["repo", "add", str(repository)], env=environment).exit_code == 0
    assert runner.invoke(app, ["index", "build"], env=environment).exit_code == 0

    neighbors = runner.invoke(
        app,
        [
            "graph",
            "neighbors",
            "run",
            "--direction",
            "outgoing",
            "--relations",
            "calls",
            "--json",
        ],
        env=environment,
    )
    traversed = runner.invoke(
        app,
        [
            "graph",
            "traverse",
            "run",
            "--depth",
            "2",
            "--relations",
            "calls",
            "--json",
        ],
        env=environment,
    )

    assert neighbors.exit_code == 0
    neighbors_payload = json.loads(neighbors.stdout)
    assert len(neighbors_payload["edges"]) == 1
    assert neighbors_payload["edges"][0]["kind"] == "calls"
    assert traversed.exit_code == 0
    assert json.loads(traversed.stdout)["depth"] == 2


def test_graph_command_rejects_unknown_relation_filter(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def run() -> None:\n    pass\n",
        encoding="utf-8",
    )
    environment = {"MONAS_LENS_DATA_DIR": str(state_dir)}

    assert runner.invoke(app, ["init"], env=environment).exit_code == 0
    assert runner.invoke(app, ["repo", "add", str(repository)], env=environment).exit_code == 0
    assert runner.invoke(app, ["index", "build"], env=environment).exit_code == 0

    result = runner.invoke(
        app,
        ["graph", "neighbors", "run", "--relations", "unknown", "--json"],
        env=environment,
    )

    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "graph_query_invalid"

    invalid_direction = runner.invoke(
        app,
        ["graph", "neighbors", "run", "--direction", "sideways", "--json"],
        env=environment,
    )
    invalid_depth = runner.invoke(
        app,
        ["graph", "traverse", "run", "--depth", "6", "--json"],
        env=environment,
    )

    assert invalid_direction.exit_code == 2
    assert json.loads(invalid_direction.stderr)["error"]["code"] == "graph_query_invalid"
    assert invalid_depth.exit_code == 2
    assert json.loads(invalid_depth.stderr)["error"]["code"] == "graph_query_invalid"
