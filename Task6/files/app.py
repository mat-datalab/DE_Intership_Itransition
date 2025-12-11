from flask import Flask, render_template, request
import psycopg
import os
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

app = Flask(__name__)

DB_CONN = os.environ.get("DB_CONN")

if not DB_CONN:
    raise RuntimeError("DB_CONN environment variable is not set")

conn = psycopg.connect(DB_CONN)

def get_db_conn():
    return psycopg.connect(DB_CONN)

@app.route("/", methods=["GET", "POST"])
def index():
    locale = "en_US"
    seed = 123
    batch_size = 10
    batch_index = 0
    users = []

    if request.method == "POST":
        locale = request.form.get("locale", locale)
        seed = int(request.form.get("seed", seed))
        batch_size = int(request.form.get("batch_size", batch_size))

        action = request.form.get("action", "generate")

        if action == "next":
            batch_index = int(request.form.get("batch_index", 0)) + 1
        else:
            batch_index = 0

        with get_db_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM generate_fake_users(%s, %s, %s, %s)",
                    (locale, seed, batch_size, batch_index),
                )
                users = cur.fetchall()

    return render_template(
        "index.html",
        locale=locale,
        seed=seed,
        batch_size=batch_size,
        batch_index=batch_index,
        users=users,
    )


if __name__ == "__main__":
    app.run(debug=True)