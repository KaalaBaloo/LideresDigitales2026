"""Modo revisión de data/test_frames/ground_truth.json.

Abre una página local (http://127.0.0.1:8765) que muestra cada imagen con sus
etiquetas y permite corregir segmentos, adultos y niños por grupo. Al guardar,
reescribe ground_truth.json y marca la imagen como revisada.

    python scripts/review_ground_truth.py [--dir data/test_frames]

Todo ocurre en tu máquina: las imágenes no salen de ella.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

SEGMENTS = ["solo", "dos_adultos", "adulto_con_ninos", "familia_numerosa", "grupo_adultos_3_6", "grupo_grande"]

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Revisión ground truth</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f4f4f2;color:#1d1d1b}
header{position:sticky;top:0;background:#1d1d1b;color:#fff;padding:10px 16px;display:flex;gap:12px;align-items:center}
main{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:16px;padding:16px}
img{width:100%;border-radius:8px;background:#ddd}
.g{background:#fff;border-radius:8px;padding:10px;margin-bottom:8px}
label{display:block;font-size:13px;margin:4px 0}
button{padding:8px 12px;border-radius:6px;border:0;background:#2f6f4f;color:#fff;cursor:pointer}
button.sec{background:#888}
.ok{color:#2f6f4f;font-weight:600}
@media(max-width:800px){main{grid-template-columns:1fr}}
</style></head><body>
<header><button class=sec onclick="go(-1)">◀</button><span id=pos></span><button class=sec onclick="go(1)">▶</button>
<span id=file></span><span id=rev></span></header>
<main><div><img id=img alt="fotograma"><p id=prompt style="font-size:12px;color:#555"></p></div>
<div><div id=groups></div><button class=sec onclick="addG()">+ grupo</button>
<p><label><input type=checkbox id=exclude> Excluir esta imagen (inservible)</label></p>
<button onclick="save()">Guardar y siguiente</button><p id=msg></p></div></main>
<script>
const SEG=%SEGMENTS%;let gt,i=0;
async function load(){gt=await (await fetch('/gt')).json();show()}
function show(){const f=gt.frames[i];pos.textContent=(i+1)+'/'+gt.frames.length;file.textContent=f.file;
rev.innerHTML=f.reviewed?'<span class=ok>✓ revisada</span>':'pendiente';img.src='/img/'+encodeURIComponent(f.file);
prompt.textContent=f.prompt||'';exclude.checked=!!f.exclude;groups.innerHTML='';(f.groups||[]).forEach(addG)}
function addG(g){g=g||{segment:'solo',adults:1,children:0};const d=document.createElement('div');d.className='g';
d.innerHTML='<label>Segmento <select>'+SEG.map(s=>'<option'+(s==g.segment?' selected':'')+'>'+s+'</option>').join('')+'</select></label>'+
'<label>Adultos <input type=number min=0 value='+g.adults+'></label><label>Niños <input type=number min=0 value='+g.children+'></label>'+
'<button class=sec onclick="this.parentNode.remove()">Quitar</button>';groups.appendChild(d)}
function go(k){i=(i+k+gt.frames.length)%gt.frames.length;show()}
async function save(){const f=gt.frames[i];f.groups=[...groups.children].map(d=>{const s=d.querySelector('select').value,n=d.querySelectorAll('input');
return{segment:s,adults:+n[0].value,children:+n[1].value}});f.reviewed=true;f.exclude=exclude.checked;
const r=await fetch('/gt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(gt)});
msg.textContent=r.ok?'Guardado':'Error al guardar';go(1)}
load();
</script></body></html>"""


def make_handler(folder: pathlib.Path):
    gt_path = folder / "ground_truth.json"

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self._send(200, PAGE.replace("%SEGMENTS%", json.dumps(SEGMENTS)).encode(), "text/html; charset=utf-8")
            elif self.path == "/gt":
                self._send(200, gt_path.read_bytes(), "application/json")
            elif self.path.startswith("/img/"):
                name = pathlib.Path(unquote(self.path[5:])).name  # sin rutas relativas
                p = folder / name
                if p.exists():
                    self._send(200, p.read_bytes(), "image/png" if p.suffix == ".png" else "image/jpeg")
                else:
                    self._send(404, b"", "text/plain")
            else:
                self._send(404, b"", "text/plain")

        def do_POST(self):
            if self.path != "/gt":
                return self._send(404, b"", "text/plain")
            body = self.rfile.read(int(self.headers["Content-Length"]))
            data = json.loads(body)
            gt_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send(200, b"{}", "application/json")

        def log_message(self, *a):
            pass

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(pathlib.Path(__file__).resolve().parents[1] / "data" / "test_frames"))
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    folder = pathlib.Path(a.dir)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(folder))
    url = f"http://127.0.0.1:{a.port}/"
    print("Revisión en", url, "(Ctrl+C para salir)")
    webbrowser.open(url)
    srv.serve_forever()


if __name__ == "__main__":
    main()
