"""scripts/apply_camera_settings.sh with a fake v4l2-ctl on PATH: one rejected setter must not stop the rest."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "apply_camera_settings.sh"
CONTROLS = ["auto_exposure", "exposure_time_absolute", "white_balance_automatic", "white_balance_temperature",
            "brightness", "contrast", "gamma", "saturation", "backlight_compensation", "power_line_frequency"]


def run_script(tmp_path, reject=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.txt"
    listing = "\n".join(f'echo "    {c} 0x0 (int) : min=0 max=100"' for c in CONTROLS)
    reject_case = ""
    if reject:
        reject_case = f'  *"--set-ctrl={reject}="*) echo "v4l2-ctl: rejected" >&2; exit 1 ;;\n'
    shim = bin_dir / "v4l2-ctl"
    shim.write_text(
        "#!/bin/bash\n"
        f'echo "$*" >> "{calls}"\n'
        'case "$*" in\n'
        f'  *--list-ctrls*) {listing}; exit 0 ;;\n'
        f"{reject_case}"
        "esac\n"
        "exit 0\n"
    )
    shim.chmod(0o755)
    device = tmp_path / "video0"
    device.touch()
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "CAMERA_DEVICE": str(device), "CAMERA_WAIT_SECONDS": "1"}
    proc = subprocess.run(["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    attempted = re.findall(r"--set-ctrl=(\w+)=", calls.read_text()) if calls.exists() else []
    return proc, attempted


def test_every_setting_is_attempted_when_one_is_rejected(tmp_path):
    proc, attempted = run_script(tmp_path, reject="saturation")
    assert sorted(attempted) == sorted(CONTROLS)
    assert proc.returncode != 0
    assert "saturation" in proc.stderr


def test_all_settings_accepted_exit_zero(tmp_path):
    proc, attempted = run_script(tmp_path)
    assert sorted(attempted) == sorted(CONTROLS)
    assert proc.returncode == 0 and "applied settings" in proc.stdout
