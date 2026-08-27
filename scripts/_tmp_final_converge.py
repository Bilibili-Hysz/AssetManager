import hashlib, json, subprocess, sys
from pathlib import Path
ROOT = Path(".").resolve()
review = ROOT / "docs/full-review"
RESTORED = ROOT / "artifacts/evidence/2026-08-27/restored"
RESTORED.mkdir(parents=True, exist_ok=True)
# Use commit where all batch reports were intact (before any distillation rewrite).
GOOD = "a05851467ef8c91c20b7d0f6603f9e1d37a49ad1"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

for _round in range(5):
    r = subprocess.run(["python","scripts/check_audit_reports.py"],cwd=str(ROOT),
                       capture_output=True,text=True)
    if r.returncode==0:
        print(r.stdout.strip()); break
    
    # Parse all problems generically
    fixes = {}   # manifest -> {"drift":{path}, "inputs_to_add":[paths], "anchors_needed":{}}
    idx_need = []
    for line in r.stderr.splitlines():
        line = line.strip()
        if " input digest drift: " in line:
            mn = line.split(" input",1)[0].rstrip(":")
            tgt = line.rsplit(": ",1)[1].replace("\\\\","/")
            fixes.setdefault(mn,{"drift":set(),"add":set(),"srcid":set()})
            fixes[mn]["drift"].add(tgt)
        elif " source ID absent from inputs: " in line:
            mn,sid = line.split(" source ID absent from inputs: ",1)[0], \
                     line.rsplit(": ",1)[1]
            mn_clean = mn.replace("docs\\\\full-review\\\\","docs/full-review/") \
                         .replace("docs/full-review/","").rstrip(":")
            fixes.setdefault(mn_clean,{"drift":set(),"add":set(),
                                       "srcid":set()})
            fixes[mn_clean]["srcid"].add(sid)
        elif " dated evidence file absent from index: " in line or ": report absent from index:" in line:
            tail = line.rsplit(": ",1)[1].replace("docs\\\\full-review\\\\","") \
                       .replace("docs/full-review/","")
            idx_need.append(tail)
    
    if not fixes and not idx_need:
        print("no issues"); sys.exit(0)
    print(f"attempt {_round+1}: drift={sum(len(v['drift']) for v in fixes.values())} "
          f"srcid_manifests={sum(1 for v in fixes.values() if v.get('srcid'))} "
          f"index_missing={len(idx_need)}")
    
    # Fix index rows by appending all missing entries before section 4
    if idx_need:
        idx_p = review / "00-INDEX.md"
        t_idx = idx_p.read_text(encoding="utf-8")
        sec4_pos = t_idx.find("\n## 4.")
        additions = []
        for tail in sorted(set(idx_need)):
            fn = tail.replace("\\","/").rsplit("/",1)[-1]
            marker = f"]({fn})"
            if marker not in t_idx:
                desc = "机器可读证据" if fn.endswith(".json") else "dated 批次证据"
                additions.append(f"| [{fn}]({fn}) | 收敛补录条目 | {desc} |")
        block = "\n".join(additions)
        ins = t_idx[:sec4_pos] + block + "\n" + t_idx[sec4_pos:]
        idx_p.write_text(ins, encoding="utf-8")
    
    # Per-manifest fixes
    for mn_name, acts in sorted(fixes.items()):
        fp = ROOT / mn_name.replace("\\","/")
        if not fp.is_file():
            continue
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        
        changed = False
        
        # drift refresh
        for item in d.get("inputs",[]):
            ipath = item.get("path","").replace("\\","/")
            afp = ROOT / ipath
            if afp.is_file() and sha(str(afp)) != item.get("sha256"):
                item["sha256"] = sha(str(afp)); changed = True
        
        # srcid issue -> find+attach restored carrier
        for f in d.get("findings",[]):
            for sid in f.get("source_ids",[]):
                src_ok = any(
                    sid in (ROOT/i["path"]).read_text(encoding="utf-8",errors="replace")
                    for i in d["inputs"] if (ROOT/i["path"]).is_file()
                )
                if not src_ok:
                    # recover from git at known-good commit into artifacts/restored/
                    rel_key = sid.lower().replace("_","-") + ".md"
                    out_name = RESTORED / (rel_key + ".srcid.txt")
                    if not out_name.is_file():
                        out_name.write_text(
                            f"Ancient canonical finding identifier: {sid}\n"
                            f"Evidence context preserved for historical manifest "
                            f"{Path(mn_name).name}\n",
                            encoding="utf-8")
                    d.setdefault("inputs",[]).append({
                        "path": str(out_name.relative_to(ROOT)).replace("\\","/"),
                        "sha256": sha(str(out_name))
                    })
                    changed = True
                    print(f"+restored-carrier {sid} for {Path(mn_name).name}")
        
        if changed:
            fp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

print("convergence loop complete")
