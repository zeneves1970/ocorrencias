import sqlite3

DB_FILE = "ocorrencias_aveiro.db"

conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

print("ObjectIDs guardados na tabela 'notificadas':")
for row in c.execute("SELECT objectid FROM notificadas"):
    print(row[0])

conn.close()
