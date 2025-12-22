import os
import dropbox
import requests
import sqlite3
import time
import atexit

def dropbox_download_db():
    token = os.environ.get("DROPBOX_TOKEN")
    if not token:
        raise RuntimeError("DROPBOX_TOKEN não definido")

    dbx = dropbox.Dropbox(token)

    try:
        dbx.files_download_to_file(DB_FILE, DROPBOX_PATH)
        print("📥 DB descarregada do Dropbox")
    except dropbox.exceptions.ApiError:
        print("📁 DB não existe no Dropbox — será criada localmente")


def dropbox_upload_db():
    token = os.environ.get("DROPBOX_TOKEN")
    if not token:
        raise RuntimeError("DROPBOX_TOKEN não definido")

    dbx = dropbox.Dropbox(token)

    with open(DB_FILE, "rb") as f:
        dbx.files_upload(
            f.read(),
            DROPBOX_PATH,
            mode=dropbox.files.WriteMode.overwrite
        )

    print("📤 DB enviada para o Dropbox")

# URL da API
URL = "https://prociv-agserver.geomai.mai.gov.pt/arcgis/rest/services/Ocorrencias_Base/FeatureServer/0/query"

# Cabeçalhos HTTP
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json"
}

# Parâmetros base da query
BASE_PARAMS = {
    "where": "CSREPC='Região de Aveiro'",
     "outFields": (
        "OBJECTID,Natureza,Concelho,EstadoAgrupado,"
        "NumeroMeiosTerrestresEnvolvidos,"
        "NumeroMeiosAereosEnvolvidos,"
        "Operacionais"
    ),
    "returnGeometry": "false",
    "f": "json",
    "resultRecordCount": 50
}

# SQLite
DB_FILE = "ocorrencias_aveiro.db"
DROPBOX_PATH = "/ocorrencias_aveiro.db"
dropbox_download_db()
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

# Fechar DB corretamente ao terminar
@atexit.register
def fechar_db():
    conn.close()

# Criar tabela se não existir
c.execute("""
CREATE TABLE IF NOT EXISTS ocorrencias (
    objectid INTEGER PRIMARY KEY,
    natureza TEXT,
    concelho TEXT,
    estado TEXT,
    meios_terrestres INTEGER,
    meios_aereos INTEGER,
    operacionais INTEGER,
    data_insercao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Tabela de histórico
c.execute("""
CREATE TABLE IF NOT EXISTS ocorrencias_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    objectid INTEGER,
    estado TEXT,
    meios_terrestres INTEGER,
    meios_aereos INTEGER,
    operacionais INTEGER,
    data_registo TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# Função para obter ocorrências da API
def obter_ocorrencias():
    ocorrencias = []
    offset = 0
    while True:
        params = BASE_PARAMS.copy()
        params["resultOffset"] = offset

        r = requests.get(URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        features = data.get("features", [])
        if not features:
            break

        ocorrencias.extend(features)
        offset += len(features)
        time.sleep(0.5)  # evita bloqueio

    return ocorrencias

def guardar_historico(attrs):
    c.execute("""
        INSERT INTO ocorrencias_historico
        (objectid, estado, meios_terrestres, meios_aereos, operacionais)
        VALUES (?, ?, ?, ?, ?)
    """, (
        attrs['OBJECTID'],
        attrs.get('EstadoAgrupado', ''),
        attrs.get('NumeroMeiosTerrestresEnvolvidos', 0),
        attrs.get('NumeroMeiosAereosEnvolvidos', 0),
        attrs.get('Operacionais', 0)
    ))
    conn.commit()

def houve_alteracao(attrs):
    """
    Verifica se houve aumento de operacionais, meios terrestres ou meios aéreos.
    Retorna True se qualquer um aumentou.
    """
    c.execute("""
        SELECT operacionais, meios_terrestres, meios_aereos
        FROM ocorrencias
        WHERE objectid = ?
    """, (attrs['OBJECTID'],))
    row = c.fetchone()
    if not row:
        return False  # não existe ainda
    oper_antes, terrestres_antes, aereos_antes = row
    return (
        attrs.get('Operacionais', 0) > oper_antes or
        attrs.get('NumeroMeiosTerrestresEnvolvidos', 0) > terrestres_antes or
        attrs.get('NumeroMeiosAereosEnvolvidos', 0) > aereos_antes
    )

# Função para guardar ocorrência no SQLite
def guardar_ocorrencia_sqlite(attrs):
    c.execute("""
        INSERT INTO ocorrencias
        (objectid, natureza, concelho, estado, meios_terrestres, meios_aereos, operacionais)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(objectid) DO UPDATE SET
            natureza=excluded.natureza,
            concelho=excluded.concelho,
            estado=excluded.estado,
            meios_terrestres=excluded.meios_terrestres,
            meios_aereos=excluded.meios_aereos,
            operacionais=excluded.operacionais
    """, (
        attrs['OBJECTID'],
        attrs.get('Natureza', ''),
        attrs.get('Concelho', ''),
        attrs.get('EstadoAgrupado', ''),
        attrs.get('NumeroMeiosTerrestresEnvolvidos', 0),
        attrs.get('NumeroMeiosAereosEnvolvidos', 0),
        attrs.get('Operacionais', 0)
    ))
    conn.commit()

def atualizar_ocorrencia(attrs):
    c.execute("""
        UPDATE ocorrencias SET
            estado = ?,
            meios_terrestres = ?,
            meios_aereos = ?,
            operacionais = ?
        WHERE objectid = ?
    """, (
        attrs.get('EstadoAgrupado', ''),
        attrs.get('NumeroMeiosTerrestresEnvolvidos', 0),
        attrs.get('NumeroMeiosAereosEnvolvidos', 0),
        attrs.get('Operacionais', 0),
        attrs['OBJECTID']
    ))
    conn.commit()

# Função principal de monitorização
def monitorizar():
    ocorrencias = obter_ocorrencias()
    novas = []
    reforcos = []

    for o in ocorrencias:
        attrs = o["attributes"]

        # Guardar histórico sempre
        guardar_historico(attrs)

        if guardar_ocorrencia_sqlite(attrs):
            novas.append(attrs)
        else:
            if houve_alteracao(attrs):
                reforcos.append(attrs)
            atualizar_ocorrencia(attrs)

    if novas:
        print(f"\n🚨 {len(novas)} nova(s) ocorrência(s) em Aveiro:\n")
        for o in sorted(novas, key=lambda x: x.get('Concelho', '')):
            print(
                f"{o.get('Concelho')} | "
                f"{o.get('Natureza')} | "
                f"{o.get('EstadoAgrupado')} | "
                f"Operacionais: {o.get('Operacionais')} | "
                f"Meios terrestres: {o.get('NumeroMeiosTerrestresEnvolvidos')} | "
                f"Meios aéreos: {o.get('NumeroMeiosAereosEnvolvidos')}"
            )

    if reforcos:
        print(f"\n🔥 Reforço de meios em {len(reforcos)} ocorrência(s):\n")
        for o in reforcos:
            print(
                f"{o.get('Concelho')} | "
                f"{o.get('Natureza')} | "
                f"{o.get('EstadoAgrupado')} | "
                f"Operacionais: {o.get('Operacionais')} | "
                f"Meios terrestres: {o.get('NumeroMeiosTerrestresEnvolvidos')} | "
                f"Meios aéreos: {o.get('NumeroMeiosAereosEnvolvidos')}"
            )

    if not novas and not reforcos:
        print("✔️ Sem novas ocorrências ou reforços em Aveiro.")

if __name__ == "__main__":
    monitorizar()

dropbox_upload_db()

