from flask import Flask, render_template, url_for, request, redirect, session
from flask_session import Session
import sqlite3

app = Flask(__name__)

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

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
        person = request.args.get('person')
        cur.execute("SELECT days.date, p1.name AS oncall, p2.name AS crisis FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE days.person_id = ? OR days.crisis_id = ? ORDER BY days.id ASC LIMIT 50", (person,person))
    else:
        cur.execute("SELECT date, p1.name AS oncall, p2.name AS crisis FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id ORDER BY days.id ASC LIMIT 50")
    rows = cur.fetchall()
    daysData = [dict(row) for row in rows]

    con.close()

    if session.get("admin") != None:
        adminPerms = session['admin']
        if adminPerms == 1:
            return render_template('index.html', people=peopleData, days=daysData, accountLink="./signin", controlText="Admin", controlLink="./account")
        else:
            return render_template('index.html', people=peopleData, days=daysData, accountLink="./signin", controlText="Swaps", controlLink="./account")
    else:
        return render_template('index.html', people=peopleData, days=daysData, accountLink="./signin")

@app.route("/signin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        if not request.form.get("password") or not request.form.get("name"):
            return "Not all fields have been filled"
        
        enteredPassword = request.form.get("password")
        enteredName = request.form.get("name")

        con = sqlite3.connect("main.db")
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        cur.execute("SELECT id, name, password, admin FROM people WHERE name = ? AND password = ?;", (enteredName, enteredPassword))
        rows = cur.fetchall()
        if (len(rows) == 0):
            return render_template('signin.html', accountLink="#", message="Incorrect Username or Password")
        peopleData = [dict(row) for row in rows]

        session['user_id'] = peopleData[0]['id']
        session['name'] = peopleData[0]['name']
        session['password'] = peopleData[0]['password']
        session['admin'] = peopleData[0]['admin']

        return redirect("/")
        
    else:
        return render_template('signin.html', accountLink="#")
    
@app.route("/account")
def account():
    if session.get("admin") != None:
        adminPerms = session['admin']
        if adminPerms == 1:
            return render_template('admin.html')
        else:
            return render_template('user.html')
    else:
        return redirect("/")