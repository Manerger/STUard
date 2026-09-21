from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from stuard.config import AppConfig
from stuard.domain.roleplan import role_specs


def test_example_config_loads(cfg: AppConfig) -> None:
    assert len(cfg.study.programmes) == 24
    assert set(cfg.study.degrees) == {"bc", "ing", "phd"}
    assert cfg.sso.enabled is False
    # 7 identity + 9 year + 19 programme roles (EN PhD programmes share SK roles; no separate degree roles)
    assert len(role_specs(cfg)) == 35


def _set_role_group(data: dict[str, Any]) -> None:
    for programme in data["study"]["programmes"]:
        if programme["id"] == "phd-iiar-en":
            programme["role_group"] = "bc-mech"


MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "duplicate_programme": lambda d: d["study"]["programmes"].append(dict(d["study"]["programmes"][0])),
    "unknown_degree": lambda d: d["study"]["programmes"][0].update(degree="mgr"),
    "bad_role_group": _set_role_group,
    "missing_identity_role": lambda d: d["roles"].pop("teacher"),
    "extra_identity_role": lambda d: d["roles"].update(dean={"name": "Dekan"}),
    "bad_timezone": lambda d: d.update(timezone="Mars/Olympus"),
    "window_after_deadline": lambda d: d["reverify"].update(window_start="11-01"),
    "impossible_date": lambda d: d["reverify"].update(deadline="02-30"),
    "bad_programme_placeholder": lambda d: d["study"]["role_names"].update(programme="{program}"),
    "bad_year_role_placeholder": lambda d: d["study"]["degrees"]["ing"].update(year_role="{rok}-ing"),
    "year_role_without_year": lambda d: d["study"]["degrees"]["bc"].update(year_role="BC"),
    "identity_role_clashes_with_year_role": lambda d: d["roles"]["student"].update(name="1-bc"),
    "unknown_key": lambda d: d.update(typo=1),
    "assign_without_status": lambda d: d["sso"]["status_rules"].append({"any_of": ["x"]}),
    "bad_color": lambda d: d["roles"]["student"].update(color="blue"),
    "bad_microsoft_tenant": lambda d: d["microsoft"].update(tenant_id="stuba.sk"),
    "empty_channel_name": lambda d: d["channels"].update(mod_review=" # "),
}


def test_channels_accept_names_and_ids(example_data: dict[str, Any]) -> None:
    example_data["channels"].update(mod_review="#admin_room_verifikacie", audit="123456789012345678", verify=42)
    channels = AppConfig.model_validate(example_data).channels
    assert (channels.mod_review, channels.audit, channels.verify) == ("admin_room_verifikacie", 123456789012345678, 42)


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_invalid_config_is_rejected(example_data: dict[str, Any], name: str) -> None:
    MUTATIONS[name](example_data)
    with pytest.raises(ValidationError):
        AppConfig.model_validate(example_data)
