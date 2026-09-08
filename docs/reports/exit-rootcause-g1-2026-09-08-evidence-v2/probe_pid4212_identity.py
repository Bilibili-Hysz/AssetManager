"""Archive the PID 4212 identity probe used by the G1 v2 report section 2.

The original 2026-09-09 01:40 query was run interactively and not archived;
this script re-executes it so the environment claim has a reproducible
record.  Windows reports a process's ORIGINAL creation time as long as it
stays alive, so re-querying now still proves continuous uptime if the PID
matches the same creation timestamp recorded in the failure evidence.
"""
import json
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parent / "pid4212-identity.json"

QUERY = (
    "Get-CimInstance Win32_Process -Filter \"ProcessId = 4212\" | "
    "Select-Object ProcessId, Name, CreationDate, CommandLine | ConvertTo-Json -Compress"
)

proc = subprocess.run(
    ["powershell", "-NoProfile", "-Command", QUERY],
    capture_output=True, text=True, errors="replace", timeout=30,
)
record = {
    "purpose": "identify the foreground PID recorded in both historical "
               "exit-timeout failure observations (observed-08, native-focus-3)",
    "query": QUERY,
    "exit_code": proc.returncode,
    "stdout": proc.stdout.strip(),
    "stderr": proc.stderr.strip() or None,
    "note": "run on 2026-09-09 to back the report's QQ.exe claim; a match of "
            "CreationDate with the 2026-09-07 12:58 timestamp quoted at 01:40 "
            "would confirm the process never restarted between then and now",
}
OUT.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(record, ensure_ascii=False, indent=1))
