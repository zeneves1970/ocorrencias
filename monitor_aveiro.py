import requests
import sqlite3
import time
import atexit

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

def houve_aumento_operacionais(attrs):
    c.execute("""
        SELECT operacionais FROM ocorrencias
        WHERE objectid = ?
    """, (attrs['OBJECTID'],))
    row = c.fetchone()
    return row and attrs.get('Operacionais', 0) > row[0]

# Função para guardar ocorrência no SQLite
def guardar_ocorrencia_sqlite(attrs):
    try:
        c.execute("""
        INSERT INTO ocorrencias 
        (objectid, natureza, concelho, estado, meios_terrestres, meios_aereos, operacionais)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            attrs['OBJECTID'],
            attrs.get('Natureza', ''),
            attrs.get('Concelho', ''),
            attrs.get('EstadoAgrupado', ''),
            attrs.get('NumeroMeiosTerrestresEnvolvidos', 0),
            attrs.get('NumeroMeiosAereosEnvolvidos', 0),
            attrs.get('Operacionais', 0)  # <-- correto
        ))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Já existe no banco
        return False

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
            if houve_aumento_operacionais(attrs):
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
