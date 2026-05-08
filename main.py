import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import pyodbc
import redis
import stripe

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

if __name__ == '__main__':
    app.run()
