from pathlib import Path

from darkflash_lcd import sensors


def hwmon(root: Path, idx: int, name: str, entries: dict[str, str]) -> None:
    d = root / "class" / "hwmon" / f"hwmon{idx}"
    d.mkdir(parents=True)
    (d / "name").write_text(name + "\n")
    for k, v in entries.items():
        (d / k).write_text(v + "\n")


def cpufreq(root: Path, khz: list[int]) -> None:
    for n, f in enumerate(khz):
        d = root / "devices" / "system" / "cpu" / f"cpu{n}" / "cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_cur_freq").write_text(f"{f}\n")


def by_id(srcs):
    return {s.id: s for s in srcs}


def test_amd_cpu_temp_prefers_tctl(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50375", "temp1_label": "Tctl",
                                   "temp3_input": "40000", "temp3_label": "Tccd1"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["cpu.temp"].read() == 50.375
    assert s["cpu.temp"].kind == "temp"


def test_intel_cpu_temp_uses_package(tmp_path):
    hwmon(tmp_path, 0, "coretemp", {"temp1_input": "61000", "temp1_label": "Package id 0",
                                    "temp2_input": "55000", "temp2_label": "Core 0"})
    assert by_id(sensors.discover(sys_root=tmp_path))["cpu.temp"].read() == 61.0


def test_gpu_and_nvme_detected(tmp_path):
    hwmon(tmp_path, 0, "nvme", {"temp1_input": "42850", "temp1_label": "Composite"})
    hwmon(tmp_path, 4, "amdgpu", {"temp1_input": "47000", "temp1_label": "edge"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["gpu.temp"].read() == 47.0
    assert s["nvme.temp"].read() == 42.85


def test_generic_hwmon_ids_are_unique(tmp_path):
    hwmon(tmp_path, 2, "spd5118", {"temp1_input": "41000"})
    hwmon(tmp_path, 3, "spd5118", {"temp1_input": "40000"})
    hwmon(tmp_path, 5, "nct6798", {"fan2_input": "1180", "fan2_label": "CPU_FAN"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["hwmon.spd5118.temp1"].read() == 41.0
    assert s["hwmon.spd5118-1.temp1"].read() == 40.0
    assert s["hwmon.nct6798.fan2"].kind == "rpm"
    assert s["hwmon.nct6798.fan2"].read() == 1180.0
    assert "CPU_FAN" in s["hwmon.nct6798.fan2"].name


def test_no_fans_means_no_rpm_sources(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50000", "temp1_label": "Tctl"})
    assert not [s for s in sensors.discover(sys_root=tmp_path) if s.kind == "rpm"]


def test_cpu_freq_avg_and_max_in_mhz(tmp_path):
    cpufreq(tmp_path, [3000000, 4000000, 5000000])
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["cpu.freq"].read() == 4000.0
    assert s["cpu.freq_max"].read() == 5000.0


def test_vanished_file_reads_none(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50000", "temp1_label": "Tctl"})
    s = by_id(sensors.discover(sys_root=tmp_path))
    (tmp_path / "class" / "hwmon" / "hwmon1" / "temp1_input").unlink()
    assert s["cpu.temp"].read() is None


def test_usage_sources_always_present(tmp_path):
    s = by_id(sensors.discover(sys_root=tmp_path))
    assert s["cpu.usage"].kind == "percent" and s["ram.usage"].kind == "percent"
    assert 0 <= s["ram.usage"].read() <= 100


def test_read_all(tmp_path):
    hwmon(tmp_path, 1, "k10temp", {"temp1_input": "50000", "temp1_label": "Tctl"})
    vals = sensors.read_all(sensors.discover(sys_root=tmp_path))
    assert vals["cpu.temp"] == 50.0
