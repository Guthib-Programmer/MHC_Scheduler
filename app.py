from flask import Flask, render_template, url_for, request
import sqlite3

app = Flask(__name__)

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

@app.route("/admin")
def admin():
    return render_template('admin.html')

if __name__ == "__main__":
    app.run(debug=True)