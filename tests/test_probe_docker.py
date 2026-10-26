"""The probe's container (D50): what the Dockerfile and compose must keep so the image runs the
same probe as the PC (headed Chrome on a virtual display, the profile in a volume at the CLI's
default place, the secrets only at run time)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "docker/probe/Dockerfile").read_text("utf-8")
COMPOSE = yaml.safe_load((ROOT / "docker/probe/compose.yaml").read_text("utf-8"))
IGNORE = (ROOT / ".dockerignore").read_text("utf-8").split()


def test_the_image_runs_the_pc_probe_on_a_virtual_display_with_the_pcs_chrome_channel():
    requires = re.search(r'requires-python\s*=\s*"(.+?)"', (ROOT / "pyproject.toml").read_text("utf-8")).group(1)
    minor = re.search(r"3\.(\d+)", requires).group(0)
    assert f"FROM python:{minor}" in DOCKERFILE, "the image's Python must be the project's"
    assert "playwright install --with-deps chrome" in DOCKERFILE      # ChromeSession: channel="chrome"
    assert "xvfb" in DOCKERFILE and '"xvfb-run"' in DOCKERFILE        # headed on a virtual screen
    assert "--headless" not in DOCKERFILE and "headless" not in DOCKERFILE.lower().replace("not headless", "")
    assert '"escapadinha", "probe"' in DOCKERFILE                     # the same command as on Windows
    assert "uv sync --frozen" in DOCKERFILE                           # the lock, not a resolution


def test_compose_keeps_the_profile_in_a_volume_and_the_secrets_out_of_the_image():
    probe = COMPOSE["services"]["probe"]
    assert probe["env_file"] == "../../.env" and "environment" not in probe
    assert probe["volumes"] == ["probe-home:/root/.pontonomada"]      # cli._probe_profile's default home
    assert COMPOSE["volumes"]["probe-home"]["name"] == "pontonomada-probe"
    assert probe["build"] == {"context": "../..", "dockerfile": "docker/probe/Dockerfile"}
    assert probe["shm_size"] == "1g" and probe["init"] is True
    for never in (".env", "data/", "output/", ".venv/", "node_modules/", ".git/"):
        assert never in IGNORE, f".dockerignore must leave out {never}"
