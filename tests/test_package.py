import subprocess
import sys

import monas_lens


def test_public_version() -> None:
    assert monas_lens.__version__ == "0.1.0.dev0"


def test_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "monas_lens", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "monas-lens 0.1.0.dev0"
