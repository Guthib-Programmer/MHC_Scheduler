from flask import Flask, render_template, url_for, request
import sqlite3

app = Flask(__name__)
app.config['DEBUG'] = True

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/", methods=["GET"])
def index():
    con = sqlite3.connect("main.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT * FROM people;")
    rows = cur.fetchall()
    peopleData = [dict(row) for row in rows]

    if request.args.get('person'):
        cur.execute("SELECT people.name, days.date FROM days JOIN people ON days.person_id = people.id WHERE people.id = ?;", request.args.get('person'))
    else:
        cur.execute("SELECT people.name, days.date FROM days JOIN people ON days.person_id = people.id;")
    rows = cur.fetchall()
    daysData = [dict(row) for row in rows]

    con.close()

    return render_template('index.html', people=peopleData, days=daysData)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if not request.form.get("password"):
            return "Not all fields have been filled"
        
        enteredPassword = request.form.get("password")

        con = sqlite3.connect("main.db")
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute("SELECT id FROM people WHERE password = ? AND admin = 1;", (enteredPassword,))
        rows = cur.fetchall()
        if (len(rows) == 0):
            return "incorrect password"
        else:
            return "correct password"
        
    else:
        return render_template('admin.html')