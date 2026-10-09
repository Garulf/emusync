import stat

import pytest

from emusync.client.config import (
    Config,
    ConfigError,
    EmulatorSettings,
    discover_slots,
    slots_for_emulator,
    write_login,
)

CONFIG = """
server_url = "http://saves.lan:8080"
token = "secret"
emudeck_root = "{root}"

[emulators.RetroArch]
states = true

[emulators.citra]
enabled = false

[emulators.ryujinx]
exclude = ["system"]

[slots."custom/thing"]
path = "{custom}"
"""


@pytest.fixture
def emudeck(tmp_path):
    saves = tmp_path / "Emulation" / "saves"
    for folder in [
        "retroarch/saves",
        "retroarch/states",
        "dolphin/GC",
        "dolphin/Wii",
        "dolphin/StateSaves",
        "xemu/saves",
        "ryujinx/saves",
        "ryujinx/system",
        "citra/saves",
        "Cemu/saves",
    ]:
        (saves / folder).mkdir(parents=True)
    (saves / "xemu" / "xbox_hdd.qcow2").write_bytes(b"big")
    (saves / ".gaming").write_text("")
    (saves / "pcsx2").mkdir()
    (saves / "pcsx2" / "saves").symlink_to(tmp_path / "missing-target")
    return tmp_path / "Emulation"


def load(tmp_path, emudeck) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(CONFIG.format(root=emudeck, custom=tmp_path / "custom"))
    return Config.load(path)


def test_load_reads_all_sections(tmp_path, emudeck):
    config = load(tmp_path, emudeck)
    assert config.server_url == "http://saves.lan:8080"
    assert config.token == "secret"
    assert config.emudeck_root == emudeck
    assert config.settings_for("retroarch") == EmulatorSettings(states=True)
    assert config.settings_for("CITRA").enabled is False
    assert config.settings_for("unknown") == EmulatorSettings()
    assert config.custom_slots == {"custom/thing": tmp_path / "custom"}


def test_missing_or_incomplete_config_raises(tmp_path):
    with pytest.raises(ConfigError):
        Config.load(tmp_path / "nope.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text('server_url = "http://x"\n')
    with pytest.raises(ConfigError):
        Config.load(bad)


def test_unsafe_custom_slot_name_raises(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text('server_url = "x"\ntoken = "y"\n[slots."../evil"]\npath = "/tmp"\n')
    with pytest.raises(ConfigError):
        Config.load(path)


def test_write_login_merges_and_restricts_permissions(tmp_path):
    path = tmp_path / "emusync" / "config.toml"
    write_login(path, "http://a:1/", "t1")
    path.write_text(path.read_text() + "\n[emulators.retroarch]\nstates = true\n")
    write_login(path, "https://b", "t2")
    config = Config.load(path)
    assert (config.server_url, config.token) == ("https://b", "t2")
    assert config.settings_for("retroarch").states is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_discover_slots_applies_rules(tmp_path, emudeck):
    slots = discover_slots(load(tmp_path, emudeck))
    assert sorted(slots) == [
        "Cemu/saves",
        "custom/thing",
        "dolphin/GC",
        "dolphin/Wii",
        "retroarch/saves",
        "retroarch/states",
        "ryujinx/saves",
        "xemu/saves",
    ]
    assert slots["dolphin/GC"] == emudeck / "saves" / "dolphin" / "GC"


def test_discover_slots_without_emudeck_returns_custom_only(tmp_path):
    config = Config("http://x", "t", tmp_path / "none", {}, {"custom/a": tmp_path})
    assert discover_slots(config) == {"custom/a": tmp_path}


def test_slots_for_emulator_is_case_insensitive(tmp_path, emudeck):
    slots = discover_slots(load(tmp_path, emudeck))
    assert sorted(slots_for_emulator(slots, "cemu")) == ["Cemu/saves"]
    assert sorted(slots_for_emulator(slots, "Dolphin")) == ["dolphin/GC", "dolphin/Wii"]
    assert slots_for_emulator(slots, "nothing") == {}


def write_config(tmp_path, body: str):
    path = tmp_path / "c.toml"
    path.write_text(body)
    return path


def test_malformed_toml_raises(tmp_path):
    with pytest.raises(ConfigError, match="c.toml"):
        Config.load(write_config(tmp_path, "server_url = "))


def test_custom_slot_without_path_raises(tmp_path):
    path = write_config(tmp_path, 'server_url = "x"\ntoken = "y"\n[slots."custom/a"]\n')
    with pytest.raises(ConfigError, match="custom/a"):
        Config.load(path)


def test_string_exclude_raises(tmp_path):
    path = write_config(
        tmp_path, 'server_url = "x"\ntoken = "y"\n[emulators.ryujinx]\nexclude = "system"\n'
    )
    with pytest.raises(ConfigError, match="ryujinx.*exclude"):
        Config.load(path)


def test_string_states_raises(tmp_path):
    path = write_config(
        tmp_path, 'server_url = "x"\ntoken = "y"\n[emulators.retroarch]\nstates = "false"\n'
    )
    with pytest.raises(ConfigError, match="retroarch.*states"):
        Config.load(path)


def test_non_string_credentials_raise(tmp_path):
    with pytest.raises(ConfigError, match="token"):
        Config.load(write_config(tmp_path, 'server_url = "x"\ntoken = 5\n'))


def test_write_login_refuses_to_overwrite_malformed_config(tmp_path):
    path = write_config(tmp_path, "server_url = ")
    with pytest.raises(ConfigError):
        write_login(path, "http://a", "t")
    assert path.read_text() == "server_url = "
