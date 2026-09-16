import base64, json, re, urllib.request, urllib.error
text = open("/seed/99_dogrula.surql", encoding="utf-8").read()
lets = "\n".join(l.strip() for l in text.splitlines() if l.strip().startswith("LET "))
blocks = re.split(r"\n(?=--\s*I\d+:)", text)
for b in blocks:
    m = re.match(r"--\s*(I14):", b)
    if not m: continue
    body = "\n".join(l for l in b.splitlines() if not l.strip().startswith("--")).strip()
    req = urllib.request.Request("http://hzk-surreal:8000/sql", data=(lets+"\n"+body).encode())
    req.add_header("Accept","application/json"); req.add_header("Content-Type","text/plain; charset=utf-8")
    req.add_header("surreal-ns","hezarfen"); req.add_header("surreal-db","zeka")
    req.add_header("Authorization","Basic "+base64.b64encode(b"root:root").decode())
    try:
        urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8","replace")[:700])
