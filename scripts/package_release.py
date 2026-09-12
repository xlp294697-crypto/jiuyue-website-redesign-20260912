"""Create an integrity-checked static release from the current clean commit."""
from pathlib import Path
import argparse, hashlib, io, json, subprocess, tarfile

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,help='Archive destination outside the source repository')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    def git(*parts):
        return subprocess.check_output(['git',*parts],cwd=root)
    if git('status','--porcelain').strip():
        raise RuntimeError('Commit and verify all source changes before packaging')
    output=Path(args.output).resolve()
    if root==output or root in output.parents:
        raise RuntimeError('Store generated release archives outside the repository')
    commit=git('rev-parse','HEAD').decode().strip()
    names=git('ls-tree','-r','--name-only','HEAD','dist').decode().splitlines()
    files={name[5:]:git('show','HEAD:'+name) for name in names}
    manifest={'commit':commit,'repository':'xlp294697-crypto/jiuyue-website-redesign-20260912','files':{name:hashlib.sha256(payload).hexdigest() for name,payload in files.items()}}
    files['release-manifest.json']=json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(output,'w:gz') as archive:
        for name,payload in sorted(files.items()):
            entry=tarfile.TarInfo(name);entry.size=len(payload);entry.mode=0o644
            archive.addfile(entry,io.BytesIO(payload))
    print(json.dumps({'commit':commit,'files':len(names),'archive_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'bytes':output.stat().st_size}))

if __name__=='__main__':main()
