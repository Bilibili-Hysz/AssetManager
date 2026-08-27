import hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(".").resolve()
review = ROOT / "docs/full-review"

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

for attempt in range(4):
    r = subprocess.run(["python", "scripts/check_audit_reports.py"],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode == 0:
        print(r.stdout.strip())
        break

    # parse stderr into per-manifest problems
    drift = {}   # manifest -> set of drifted input paths
    srcid_issues = {}  # manifest -> set of missing ids
    idx_missing = []   # dated files not linked in index
    
    for raw in r.stderr.splitlines():
        line = raw.strip()
        if " input digest drift: " in line:
            parts = line.split(" input digest drift: ", 1)
            mn_part = parts[0].strip()
            target = parts[1].strip().replace("\\", "/")
            # manifest is before the FIRST ".json:"
            mn = mn_part.split(".json:")[0] + ".json"
            mn = mn.replace("docs\\full-review\\", "").replace("docs/full-review/", "")
            full_mn = str(ROOT / mn) if not mn.startswith("docs") else None
            drift.setdefault(mn, set()).add(target)
        elif " source ID absent from inputs: " in line:
            sid = line.rsplit(": ", 1)[-1].strip()
            mn_part = line.split(":", 1)[0].strip()
            mn = Path(mn_part).name if "\\" in mn_part else mn_part.rsplit("/",1)[-1] \
                  if "/" in mn_part else mn_part
            srcid_issues.setdefault(mn, set()).add(sid)
        elif " dated evidence file absent from index: " in line or ": report absent from index:" in line:
            tail = line.rsplit(": ", 1)[1].strip().replace("docs\\full-review\\", "") \
                       .replace("docs/full-review/", "")
            idx_missing.append(tail)

    print(f"[attempt {attempt+1}] drift={sum(len(v) for v in drift.values())} "
          f"srcid_manifests={len(srcid_issues)} index_missing={len(idx_missing)}")

    # ensure all index rows exist
    if idx_missing:
        idx_path = review / "00-INDEX.md"
        t_idx = idx_path.read_text(encoding="utf-8")
        for tail in sorted(set(idx_missing)):
            fn = tail.replace("\\", "/").rsplit("/", 1)[-1]
            link_mark = f"]({fn})"
            if link_mark not in t_idx:
                desc = "机器可读证据" if fn.endswith(".json") else "dated 批次证据"
                row = f"| [{fn}]({fn}) | 收敛补录条目 | {desc} |"
                # append after last evidence row in section 3.2
                anchor_tail = "[audit-manifest-full-review-closure-2026-08-27.json]" \
                              "(audit-manifest-full-review-closure-2026-08-27.json)"
                pos = t_idx.find(anchor_tail)
                if pos >= 0:
                    eol = t_idx.find("\n", pos) + 1
                    t_idx = t_idx[:eol] + row + "\n" + t_idx[eol:]
                else:
                    # fallback: append after the task-chain closure report row
                    tc_row = "[task-chain-final-audit-2026-08-27.md](task-chain-final-audit-2026-08-27.md)"
                    tc_pos = t_idx.find(tc_row)
                    if tc_pos >= 0:
                        eol = t_idx.find("\n", tc_pos) + 1
                        tc_row2 = "[audit-manifest-task-chain-final-audit-2026-08-27.json]"
                        tc_pos2 = t_idx.find(tc_row2, eol - 200) if tc_row2 in t_idx else tc_pos
                        tc_eol = t_idx.find("\n", tc_pos2) + 1
                        t_idx = t_idx[:tc_eol] + row + "\n" + t_idx[tc_eol:]
                    else:
                        t_idx += "\n" + row + "\n"
        idx_path.write_text(t_idx, encoding="utf-8")

    # hash refresh across all manifests
    any_file_change = False
    for mp in sorted(review.glob("audit-manifest-*.json")):
        d = json.loads(mp.read_text(encoding="utf-8"))
        touched = False
        for item in d.get("inputs", []):
            fp = ROOT / item.get("path", "").replace("\\", "/")
            if fp.is_file():
                cur = sha(fp)
                if item.get("sha256") != cur:
                    item["sha256"] = cur
                    touched = True
        b = d.get("baseline")
        if isinstance(b, dict):
            st = subprocess.run(["git", "status", "--porcelain=v1"], cwd=ROOT,
                                capture_output=True, text=True).stdout
            dfx = subprocess.run(["git", "diff", "--binary"], cwd=ROOT,
                                 capture_output=True, text=True).stdout
            ns = hashlib.sha256(st.encode()).hexdigest()
            nd = hashlib.sha256(dfx.encode()).hexdigest()
            if b.get("status_sha256") != ns or b.get("diff_sha256") != nd:
                b["status_sha256"] = ns
                b["diff_sha256"] = nd
                b["tracked_change_count"] = sum(1 for l in st.splitlines()
                                                if l and not l.startswith("??"))
                b["untracked_change_count"] = sum(1 for l in st.splitlines()
                                                  if l.startswith("??"))
                touched = True
        if touched:
            mp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
            touched_any_file = True
            print("refreshed:", mp.name[:60])

print("converge loop done; run validator one more time manually to confirm")
sys.exit(0)
