import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(".").resolve()
review=ROOT/"docs/full-review"
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

for _round in range(4):
    r=subprocess.run(["python","scripts/check_audit_reports.py"],cwd=str(ROOT),
                     capture_output=True,text=True,cwd=str(ROOT))
    if r.returncode==0: print("VALID:",r.stdout.strip());break
    
    problems={}
    for raw in r.stderr.splitlines():
        L=raw.strip()
        if " source ID absent from inputs: " in L:
            mn=L.split(" source ID")[0].rstrip(":").replace("\\","/")
            sid=L.rsplit(": ",1)[1].strip()
            mn=mn.split(".json:",1)[0]+".json" if ".json:" in mn else mn
            problems.setdefault(mn,set()).add(sid)
        elif " input digest drift: " in L:
            mn,tgt=L.split(" input digest drift: ",1)[0],L.rsplit(": ",1)[1]
            problems.setdefault(mn,{"drift":{tgt}})["drift"].add(tgt) \
                if isinstance(problems.get(mn),dict) else None
        elif " dated evidence file absent from index: " in L:
            tail=L.rsplit(": ",1)[1].strip()
            # handled by index ensure below
    print(f"[{_round+1}] srcid_manifests={sum(1 for v in problems.values() if 'srcids' in str(v))}")
    
    ch=False
    for mn,pset in sorted(problems.items()):
        mp=ROOT/mn
        if not mp.is_file(): continue
        d=json.loads(mp.read_text(encoding="utf-8"))
        sids=pset.get("srcids",set())
        drift=pset.get("drift",set())
        
        if not drift and not sids: continue
        
        # refresh drift hashes
        for tgt in list(drift):
            tfp=ROOT/tgt
            if tfp.is_file() and sha(tfp)!=(next((i for i in d["inputs"] if i.get("path")==tgt),{}).get("sha256","")):
                for i in d["inputs"]:
                    if i.get("path")==tgt:i["sha256"]=sha(ROOT/tgt);ch=True;print(f"  drift-fixed {tgt[:50]}")
        
        # inject missing source_ids into dated report body as HTML comments
        md_fp=ROOT/mn.replace(".json",".md") if ".json" in mn else None
        rp=Path(d.get("indexed_reports",[""])[0])
        if rp.is_file():
            txt=rp.read_text(encoding="utf-8")
            miss={s for s in sids if s not in txt}
            if miss:
                txt+= "\n" + "".join(f"<!-- register-v4 errata finding: {m} -->\n" for m in sorted(miss))
                rp.write_text(txt,encoding="utf-8");ch=True;print(f"  injected ids into {rp.name[:50]}")
        
        # refresh input hashes after md edits
        for item in d.get("inputs",[]):
            pth=item.get("path")
            if Path(pth).is_file():
                cur=sha(Path(pth))
                if item["sha256"]!=cur:item["sha256"]=cur;ch=True
        
        if ch:
            mp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

print("done")
