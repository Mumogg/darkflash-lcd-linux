from darkflash_lcd.config import DEFAULT_FIELDS, Config, load, save


def test_missing_file_gives_defaults(tmp_path):
    cfg, err = load(tmp_path / "nope.toml")
    assert cfg == Config() and err is None
    assert cfg.fields == DEFAULT_FIELDS


def test_roundtrip(tmp_path):
    p = tmp_path / "c" / "config.toml"
    cfg = Config(interval_ms=250, unit="F", fields=("gpu.temp", "cpu.usage", "cpu.temp", "hwmon.nct6798.fan2"))
    save(p, cfg)
    assert load(p) == (cfg, None)


def test_invalid_toml_returns_defaults_and_error(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("interval_ms = [oops")
    cfg, err = load(p)
    assert cfg == Config() and err


def test_bad_values_are_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('interval_ms = 10\nunit = "K"\nfields = ["a"]\n')
    cfg, err = load(p)
    assert cfg == Config() and "interval_ms" in err


def test_quotes_in_ids_survive(tmp_path):
    p = tmp_path / "config.toml"
    cfg = Config(fields=('hwmon.a"b.temp1', "cpu.usage", "ram.usage", "cpu.freq"))
    save(p, cfg)
    assert load(p)[0] == cfg
