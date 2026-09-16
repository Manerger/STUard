from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from stuard.config import AppConfig
from stuard.db.connection import connect
from stuard.db.migrate import migrate
from stuard.db.repos import Repo

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_data() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def cfg(example_data: dict[str, Any]) -> AppConfig:
    return AppConfig.model_validate(example_data)


@pytest.fixture
async def repo() -> AsyncIterator[Repo]:
    conn = await connect(":memory:")
    await migrate(conn)
    r = Repo(conn)
    yield r
    await r.close()
