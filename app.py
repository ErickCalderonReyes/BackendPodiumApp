import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import pyodbc
import redis
import stripe

#hh
app = Flask(__name__)
# Permitimos el acceso solo desde tu URL de Angular configurada en Azure
CORS(app, origins=[os.environ.get('CORS_ORIGIN')])

# Configuración de Stripe
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Función para conectar a Azure SQL
def get_db_connection():
    # Azure App Service Linux ya tiene instalado el driver ODBC 18 o 17
    conn_str = os.environ.get('AZURE_SQL_CONNECTIONSTRING')
    return pyodbc.connect(conn_str)

# Función para conectar a Redis
cache = redis.StrictRedis(
    host=os.environ.get('REDIS_HOST'),
    port=6380,
    password=os.environ.get('REDIS_KEY'),
    ssl=True
)

@app.route('/')
def health_check():
    return jsonify({"status": "Podium API Online", "version": "1.0.0"}), 200

@app.route('/candidates', methods=['GET'])
def get_candidates():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT Id, FullName, Country, PhotoUrl, TotalVotes FROM Candidates")
        
        candidates = []
        for row in cursor.fetchall():
            candidates.append({
                "id": row.Id,
                "name": row.FullName,
                "country": row.Country,
                "photo": row.PhotoUrl,
                "votes": row.TotalVotes
            })
        conn.close()
        return jsonify(candidates)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health')
def health_check():
    health_status = {
        "status": "online",
        "python_version": os.sys.version,
        "pyodbc_status": "not_tested",
        "available_drivers": pyodbc.drivers(),
        "database_connection": "not_tested"
    }
    
    try:
        # Intentamos importar pyodbc (la prueba de fuego original)
        health_status["pyodbc_status"] = "installed"
        
        # Intentamos una conexión rápida usando tu variable de entorno
        # Asegúrate de que en Azure la variable se llame AZURE_SQL_CONNECTIONSTRING
        conn_str = os.getenv('AZURE_SQL_CONNECTIONSTRING')
        if conn_str:
            conn = pyodbc.connect(conn_str, timeout=5)
            conn.close()
            health_status["database_connection"] = "success"
        else:
            health_status["database_connection"] = "error: connection string missing"
            
    except Exception as e:
        health_status["pyodbc_status"] = "error"
        health_status["error_message"] = str(e)
    
    return jsonify(health_status)

if __name__ == '__main__':
    app.run()
