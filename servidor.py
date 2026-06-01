#!/usr/bin/env python3
"""
ML2 Ramal 2 — Servidor local Flask
Procesa PDFs de cargas de trabajo SEAT y devuelve JSON al dashboard
"""
import os, re, json, subprocess, tempfile, glob

# Buscar pdftotext
def find_pdftotext():
    import shutil
    p = shutil.which('pdftotext')
    if p: return p
    # Buscar en carpetas locales (Windows)
    base = os.path.dirname(os.path.abspath(__file__))
    patterns = [
        os.path.join(base, 'poppler*', 'Library', 'bin', 'pdftotext.exe'),
        os.path.join(base, 'poppler*', 'bin', 'pdftotext.exe'),
    ]
    for pat in patterns:
        matches = glob.glob(pat)
        if matches: return matches[0]
    return 'pdftotext'

PDFTOTEXT = find_pdftotext()
print(f"pdftotext: {PDFTOTEXT}")
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

PORT = int(os.environ.get('PORT', 5000))

NOMBRES = {
    '2047':'Cristales','2063':'Custodias','2073':'Tubos freno 1',
    '2083':'Tubos freno 2','2087':'Conexión BCM','2101':'Tubos freno 3',
    '2105':'Moldura portón','2111':'Masas motor','2113':'Batería MHEV',
    '2123':'Cin. anterior','2125':'Soportes','2127':'Cin. anterior 2',
    '2137':'Airbag izq','2143':'Airbag der','2151':'Motor limpia',
    '2159':'Raku 1','2163':'Masas der','2167':'Masas izq',
    '2171':'Centralita','2183':'Tubos sup','2193':'Tubos inf',
    '2195':'Piloto móvil','2199':'Raku-asideros',
    '2223':'Taster','2235':'Montante B Izquierdo','2243':'Taster 1',
    '2247':'Escobilla','2251':'Tubos','2253':'Montante B Derecho',
    '2263':'Motor','2267':'Transformador','2273':'Consola motor',
    '2277':'Tornillos Cinturón Izquierdo','2287':'MPS 1 (HI)',
    '2298':'Tornillos Cinturón Derecho','2327':'Spoiler','2335':'Filtro',
    '2337':'Marco','2338':'Insonorizante','2353':'Anilla Carga Izquierda',
    '2363':'Marco Central Portón (HI)','2377':'Desconexión',
    '2383':'Tuberías','2499':'Formación',
}
EXCLUIR = {'2292','2294','2297','2299','2438','2446','2462'}

PR_RE = re.compile(r'^([ADILS]\s+\d+[´\']?|[EM]\d{6,7}|\d{4,7})')
SKIP  = re.compile(r'KSU:|Carga de Trabajo|Fábrica|Clase Coche:|Zona de fab|'
                   r'Supervisor\s*:|Tacto:\s+L\d|Logistica|Ultima Mod|Procesos:|'
                   r'Superv\.|Pres\.Sind|IE:|OPERARIO|[AÁ]rea:|Fecha de imp|'
                   r'Plan:\s+5F|Activos|Tpo\.Tacto|MOD:|F-Zeit|Inicio:')

def limpiar(pr): return re.sub(r'[´\'\s]+$','',pr).strip()

def get_tiempo(text):
    m3=re.search(r'\b(\d+,\d{3,4})\s+\d+,\d+\s+\d+,\d{3,4}\b',text)
    if m3: return float(m3.group(1).replace(',','.'))
    m2=re.search(r'\b(\d+,\d{3,4})\s+\d+,\d+\b',text)
    if m2: return float(m2.group(1).replace(',','.'))
    m1=re.search(r'\b(\d+,\d{3,4})\b',text)
    if m1: return float(m1.group(1).replace(',','.'))
    return None

def get_tacto(lines, start):
    for l in lines[start:start+15]:
        m = re.search(r'Tpo\.Tacto:\s*([\d,]+)\s*min', l)
        if m: return float(m.group(1).replace(',','.'))
    return None

def extraer_ops(lines, carga_num, start, end):
    block = lines[start:end]
    first_op = None
    for j,l in enumerate(block):
        if 'Operacion:' in l and 'Descripci' in l:
            first_op=j+1; break
    if first_op is None: return []

    ops=[]; seen_p=set()
    cur_pr=None; cur_desc_parts=[]; t_todos=None; in_103=True

    def flush():
        nonlocal cur_pr,cur_desc_parts,t_todos
        if not cur_pr: return
        pr_c=limpiar(cur_pr)
        if pr_c in seen_p: return
        seen_p.add(pr_c)
        if re.match(r'^S\s+\d',pr_c): return
        desc=' '.join(p.strip() for p in cur_desc_parts if p.strip())
        if t_todos is None: return
        ops.append({'pr':pr_c,'desc':desc,'TODOS':t_todos})

    for j in range(first_op,len(block)):
        raw=block[j].rstrip()
        if SKIP.search(raw): continue
        if 'Operacion:' in raw and 'Descripci' in raw: continue
        if re.search(r'\bAP021101\b|\bAP021104\b',raw): in_103=False; continue
        if 'AP021103' in raw: in_103=True; continue
        if not in_103: continue
        m_c=re.search(r'\b(5F[FN])\b',raw)
        pr_m=PR_RE.match(raw[:23].strip())
        if pr_m:
            pr_new=pr_m.group(1).strip(); pr_c=limpiar(pr_new)
            if re.match(r'^S\s+',pr_c):
                num=re.search(r'\d+',pr_c).group()
                if num!=carga_num: continue
            if pr_c not in seen_p:
                flush()
                desc_part=raw[23:m_c.start()].strip() if m_c else raw[23:70].strip()
                cur_pr=pr_new; cur_desc_parts=[desc_part]; t_todos=None
            if m_c and t_todos is None:
                t=get_tiempo(raw[m_c.end():])
                if t is not None: t_todos=t
        elif m_c and cur_pr:
            pre=raw[:m_c.start()].strip()
            if pre and len(pre)>2 and not re.match(r'^[\d\s,\.%\+]+$',pre) and not pre.startswith('-'):
                cur_desc_parts.append(pre)
        elif raw.strip() and cur_pr:
            txt=raw.strip()
            if len(txt)>2 and not re.match(r'^[-\s\d,\.]+$',txt) and not txt.startswith('-'):
                cur_desc_parts.append(txt)
    flush()
    return ops

def procesar_pdf(pdf_bytes):
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(pdf_bytes); pdf_path=f.name
    try:
        txt_path = pdf_path.replace('.pdf','.txt')
        # Pasar la carpeta bin de poppler en el entorno del proceso
        env = os.environ.copy()
        _bin = os.path.dirname(PDFTOTEXT)
        env['PATH'] = _bin + os.pathsep + env.get('PATH', '')
        r = subprocess.run([PDFTOTEXT, '-layout', '-colspacing', '1', pdf_path, txt_path],
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           env=env)
        if r.returncode != 0:
            raise RuntimeError(f'pdftotext error (rc={r.returncode}): stdout={r.stdout!r} stderr={r.stderr!r}')
        with open(txt_path,'r',encoding='utf-8',errors='replace') as f:
            lines = f.readlines()
        os.remove(txt_path)
    finally:
        os.remove(pdf_path)

    seen_c=set(); starts=[]
    for i,line in enumerate(lines):
        m=re.search(r'Carga\s*:\s*(\d+)\b',line)
        if not m: continue
        c=m.group(1)
        if c in seen_c or c in EXCLUIR: continue
        block=''.join(lines[i:i+10])
        m_ops=re.search(r'Operarios:\s+([\d.]+)',block)
        if not m_ops or float(m_ops.group(1))==0: continue
        if re.search(r'(GRC|PORTAVOZ|REPARADOR|CONDUCTOR|INSTALACI|F4F)',block): continue
        seen_c.add(c); starts.append((c,i))

    orden_dict={}
    for idx,(c,s) in enumerate(starts):
        end=starts[idx+1][1] if idx+1<len(starts) else len(lines)
        orden_dict[c]=(s,end)

    cargas=[]
    for carga in sorted(orden_dict.keys(),key=int):
        nombre=NOMBRES.get(carga,f'Carga {carga}')
        start,end=orden_dict[carga]
        tacto=get_tacto(lines,start)
        ops=extraer_ops(lines,carga,start,end)
        total=round(sum(op['TODOS'] or 0 for op in ops),3)
        tab=f"{carga} {nombre}"[:28]
        ops_json=[{'pr':op['pr'],'desc':op['desc'],'TODOS':op['TODOS']} for op in ops]
        cargas.append({
            'id':tab,'num':carga,'nombre':nombre,
            'cols':['TODOS'],'ops':ops_json,
            'totales':{'TODOS':total},'n_ops':len(ops),
            'tacto_pdf':tacto
        })
        print(f"  ✓ {carga} {nombre[:20]:20} | {len(ops)} ops | tacto={tacto} | {total:.3f}")

    return cargas, orden_dict

@app.route('/')
def index():
    # Intentar index.html primero, luego dashboard_planta.html
    import os
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'index.html')):
        return send_from_directory('.', 'index.html')
    return send_from_directory('.', 'dashboard_planta.html')

@app.route('/health')
def health():
    r = subprocess.run([PDFTOTEXT, '-v'], capture_output=True)
    pdftotext_ok = r.returncode==0 or b'pdftotext' in r.stderr
    return jsonify({'ok':True,'pdftotext':pdftotext_ok})

@app.route('/procesar-pdf', methods=['POST'])
def procesar_pdf_route():
    if 'pdf' not in request.files:
        return jsonify({'error':'No se recibió PDF'}), 400
    f = request.files['pdf']
    if not f.filename.lower().endswith('.pdf'):
        return jsonify({'error':'Debe ser un PDF'}), 400

    print(f"\n📄 Procesando: {f.filename}")
    try:
        cargas, _ = procesar_pdf(f.read())
        escenario = 'A'
        if cargas and cargas[0].get('tacto_pdf'):
            escenario = 'A' if cargas[0]['tacto_pdf'] <= 1.5 else 'B'
        print(f"  Total: {len(cargas)} cargas → Escenario {escenario}")
        return jsonify({'ok':True,'cargas':cargas,'total':len(cargas),'escenario':escenario})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error':str(e)}), 500

if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════╗
║  ML2 RAMAL 2 — Servidor PDF             ║
╠══════════════════════════════════════════╣
║  Abre: http://localhost:{PORT}             ║
║  Ctrl+C para parar                      ║
╚══════════════════════════════════════════╝
""")
    app.run(host='0.0.0.0', port=PORT, debug=False)
