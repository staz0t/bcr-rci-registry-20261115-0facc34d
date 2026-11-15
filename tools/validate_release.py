#!/usr/bin/env python3
import base64, hashlib, json, os, pathlib, re, subprocess, sys, urllib.parse, urllib.request

base, output = sys.argv[1:]
head = os.environ["PR_HEAD"]
token = os.environ["GITHUB_TOKEN"]
changed = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD"], text=True).splitlines()
expected = {"modules/proof/metadata.json", "modules/proof/1.0.0/MODULE.bazel", "modules/proof/1.0.0/source.json"}
if set(changed) != expected:
    raise SystemExit(f"unexpected reviewed files: {changed}")
source = json.loads(pathlib.Path("modules/proof/1.0.0/source.json").read_text())
metadata = json.loads(pathlib.Path("modules/proof/metadata.json").read_text())
match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/([^/]+)", source.get("url", ""))
if not match:
    raise SystemExit("source URL is not one GitHub release asset")
owner, repo, tag, asset_name = map(urllib.parse.unquote, match.groups())
if metadata.get("repository") != [f"github:{owner}/{repo}"]:
    raise SystemExit("metadata repository does not match source URL")
headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "bcr-release-identity-review"}
def api(path):
    with urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{owner}/{repo}/{path}", headers=headers), timeout=120) as response:
        return json.load(response)
release = api(f"releases/tags/{urllib.parse.quote(tag, safe='')}")
assets = [item for item in release["assets"] if item["name"] == asset_name and item["browser_download_url"] == source["url"]]
if len(assets) != 1 or release["tag_name"] != tag or release["target_commitish"] != "main":
    raise SystemExit("release/tag/asset identity mismatch")
asset = assets[0]
with urllib.request.urlopen(urllib.request.Request(source["url"], headers={"User-Agent": "bcr-release-identity-review", "Cache-Control": "no-cache"}), timeout=120) as response:
    payload = response.read()
sha = hashlib.sha256(payload).hexdigest()
integrity = "sha256-" + base64.b64encode(bytes.fromhex(sha)).decode()
if source.get("integrity") != integrity or len(payload) != asset["size"]:
    raise SystemExit("reviewed source package fails integrity or size")
ref = api(f"git/ref/tags/{urllib.parse.quote(tag, safe='')}")["object"]
if ref["type"] == "tag":
    ref = api(f"git/tags/{ref['sha']}")["object"]
if ref["type"] != "commit":
    raise SystemExit("release tag does not resolve to a commit")
branch = api("branches/main")["commit"]["sha"]
if branch != ref["sha"]:
    raise SystemExit("source main already differs from release tag during review")
receipt = {
    "pr_head": head, "source_url": source["url"], "source_integrity": source["integrity"], "source_sha256": sha,
    "release_id": release["id"], "release_tag_name": release["tag_name"], "release_target_commitish": release["target_commitish"],
    "release_immutable": bool(release.get("immutable", False)), "tag_commit": ref["sha"], "target_branch_commit": branch,
    "source_asset_id": asset["id"], "source_asset_name": asset["name"], "source_asset_url": asset["browser_download_url"],
    "source_asset_size": asset["size"], "source_asset_updated_at": asset["updated_at"],
}
pathlib.Path(output).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
print(f"PASS reviewed release/tag/main A {ref['sha']} package {sha}")
