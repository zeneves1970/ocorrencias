import requests
import sqlite3
import time
import os
import signal
import dropbox
from datetime import datetime

# --------------------------------------------------
# Configurações API
# --------------------------------------------------
URL = "https://prociv-agserver.geomai.mai.gov.pt/arcgis/rest/services/Ocorrencias_Base/FeatureServer/0/query"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}

BASE_PARAMS = {
    "where": """
        CSREPC='Região de Aveiro'
        OR Concelho='Oliveira de Azeméis'
        OR Concelho='Santa Maria da Feira'
        OR Concelho='Arouca'
        OR Concelho='Espinho'
        OR Concelho='Castelo de Paiva'
        OR Concelho='São João da Madeira'
        OR Concelho='Vale de Cambra'
    """,
    "outFields": "*",
    "returnGeometry": "false",
    "f": "json",
    "resultRecordCount": 50
}

# --------------------------------------------------
# Ficheiros / Dropbox
# --------------------------------------------------
DB_FILE = "ocorrencias_aveiro.db"
DROPBOX_PATH = "/ocorrencias_aveiro.db"

# --------------------------------------------------
# Telegram
# --------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def enviar_telegram(mensagem: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram não configurado")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "HTML"
    }

    r = requests.post(url, json=payload, timeout=15)
    if r.status_code == 200:
        print("📨 Alerta enviado para o Telegram")
    else:
        print(f"❌ Erro Telegram: {r.text}")

# --------------------------------------------------
# Dropbox
# --------------------------------------------------
def baixar_db():
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN"),
        app_key=os.environ.get("DROPBOX_APP_KEY"),
        app_secret=os.environ.get("DROPBOX_APP_SECRET"),
    )
    try:
        metadata, res = dbx.files_download(DROPBOX_PATH)
        with open(DB_FILE, "wb") as f:
            f.write(res.content)
        print("📥 DB descarregada do Dropbox")
    except dropbox.exceptions.ApiError:
        print("⚠️ DB não existe no Dropbox — será criada localmente")

def enviar_db():
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=os.environ.get("DROPBOX_REFRESH_TOKEN"),
        app_key=os.environ.get("DROPBOX_APP_KEY"),
        app_secret=os.environ.get("DROPBOX_APP_SECRET"),
    )
    with open(DB_FILE, "rb") as f:
        dbx.files_upload(
            f.read(),
            DROPBOX_PATH,
            mode=dropbox.files.WriteMode.overwrite
        )
    print("📤 DB enviada para o Dropbox")

# --------------------------------------------------
# Inicialização DB
# --------------------------------------------------
baixar_db()
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS ocorrencias (
    objectid INTEGER PRIMARY KEY,
    DataInicioOcorrencia TEXT,
    natureza TEXT,
    concelho TEXT,
    estado TEXT,
    operacionais INTEGER,
    meios_terrestres INTEGER,
    meios_aereos INTEGER,
    data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

# Tabela APENAS para controlo de alertas (fingerprint lógico)
c.execute("""
CREATE TABLE IF NOT EXISTS notificadas (
    fingerprint TEXT PRIMARY KEY
)
""")
conn.commit()

# --------------------------------------------------
# Obter ocorrências da API
# --------------------------------------------------
def obter_ocorrencias():
    ocorrencias = []
    offset = 0

    while True:
        params = BASE_PARAMS.copy()
        params["resultOffset"] = offset

        r = requests.get(URL, params=params, headers=HEADERS, timeout=60)
        r.raise_for_status()

        data = r.json()
        features = data.get("features", [])

        if not features:
            break

        ocorrencias.extend(features)
        offset += len(features)
        time.sleep(0.5)

    return ocorrencias

# --------------------------------------------------
# Guardar ocorrência + alerta Telegram
# --------------------------------------------------
def guardar_ocorrencia(attrs):
    objectid = attrs["OBJECTID"]

    data_inicio = attrs.get("DataInicioOcorrencia", "")
    concelho = attrs.get("Concelho", "")
    natureza = attrs.get("Natureza", "")

    # Fingerprint lógico da ocorrência
    fingerprint = f"{data_inicio}|{concelho}|{natureza}"

    # Verificar se já foi notificada
    ja_notificada = c.execute(
        "SELECT 1 FROM notificadas WHERE fingerprint=?",
        (fingerprint,)
    ).fetchone()

    # Guardar / atualizar ocorrência (OBJECTID continua a ser usado aqui)
    c.execute("""
        INSERT INTO ocorrencias
        (objectid, DataInicioOcorrencia, natureza, concelho, estado,
         operacionais, meios_terrestres, meios_aereos, data_atualizacao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(objectid) DO UPDATE SET
            DataInicioOcorrencia=excluded.DataInicioOcorrencia,
            natureza=excluded.natureza,
            concelho=excluded.concelho,
            estado=excluded.estado,
            operacionais=excluded.operacionais,
            meios_terrestres=excluded.meios_terrestres,
            meios_aereos=excluded.meios_aereos,
            data_atualizacao=CURRENT_TIMESTAMP
    """, (
        objectid,
        data_inicio,
        natureza,
        concelho,
        attrs.get("EstadoAgrupado", ""),
        attrs.get("Operacionais", 0),
        attrs.get("NumeroMeiosTerrestresEnvolvidos", 0),
        attrs.get("NumeroMeiosAereosEnvolvidos", 0),
    ))

    # Enviar alerta Telegram APENAS se fingerprint for novo
    if not ja_notificada:
        mensagem = (
            "🚨 <b>Nova ocorrência</b>\n\n"
            f"🕒 {data_inicio.replace('T',' ')}\n"
            f"📍 {concelho}\n"
            f"🔥 {natureza}\n"
            f"📊 Estado: {attrs.get('EstadoAgrupado','')}\n"
            f"👨‍🚒 Operacionais: {attrs.get('Operacionais',0)}\n"
            f"🚒 Meios T.: {attrs.get('NumeroMeiosTerrestresEnvolvidos',0)}\n"
            f"🚁 Meios A.: {attrs.get('NumeroMeiosAereosEnvolvidos',0)}"
        )
        enviar_telegram(mensagem)

        c.execute(
            "INSERT INTO notificadas (fingerprint) VALUES (?)",
            (fingerprint,)
        )

    conn.commit()

# --------------------------------------------------
# Limpeza (10 dias)
# --------------------------------------------------
def apagar_antigas():
    c.execute("""
        DELETE FROM ocorrencias
        WHERE data_atualizacao < datetime('now', '-10 days')
    """)
    conn.commit()

# --------------------------------------------------
# Monitorização
# --------------------------------------------------
def monitorizar():
    ocorrencias = obter_ocorrencias()

    for o in ocorrencias:
        guardar_ocorrencia(o["attributes"])

    apagar_antigas()
    enviar_db()

    print(f"✔️ {len(ocorrencias)} ocorrências processadas")

# --------------------------------------------------
# Execução
# --------------------------------------------------
if __name__ == "__main__":
    import os
    import signal

    def watchdog_ping():
        try:
            os.kill(1, signal.SIGUSR1)  # avisa o systemd que o script está vivo
        except Exception:
            pass

    while True:
        try:
            monitorizar()
            watchdog_ping()  # avisa o systemd
        except Exception as e:
            print(f"❌ Erro: {e}")
        time.sleep(300)  # espera 300 segundos antes da próxima execução
