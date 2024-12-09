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
def signin():
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

        con.close()

        session['user_id'] = peopleData[0]['id']
        session['name'] = peopleData[0]['name']
        session['password'] = peopleData[0]['password']
        session['admin'] = peopleData[0]['admin']

        return redirect("/")
        
    else:
        return render_template('signin.html', accountLink="#")
    
@app.route("/account", methods=['GET', 'POST'])
def account():
    if session.get("admin") != None:
        adminPerms = session['admin']
        personId = session['user_id']

        if request.method == "POST":
            if not request.form.get("daySelect"):
                return "Empty Field"
            
            selected_days = request.form.getlist('daySelect')
            if len(selected_days) != 2:
                return "Wrong number of days selected"
            
            con = sqlite3.connect("main.db")
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            cur.execute("SELECT * FROM days WHERE id = ?", (selected_days[0],))
            dayData = cur.fetchone()
            dayDataList = dict(dayData)

            selfDay = False
            day1Id = 0
            day2Id = 0

            if request.form.get("crisis"):
                if dayDataList['crisis_id'] == personId:
                    selfDay = True
                    day1Id = selected_days[0]
            else:
                if dayDataList['person_id'] == personId:
                    selfDay = True
                    day1Id = selected_days[0]

            cur.execute("SELECT * FROM days WHERE id = ?", (selected_days[1],))
            dayData = cur.fetchone()
            dayDataList = dict(dayData)

            if request.form.get("crisis"): # TODO: Change return statements to return to a error page
                if dayDataList['crisis_id'] == personId:
                    if selfDay:
                        return "Cannot select two days of your own"
                    else:
                        day1Id = selected_days[1]
                        day2Id = selected_days[0]
                else:
                    if selfDay:
                        day2Id = selected_days[1]
                    else:
                        return "One of the days must be your own"
            else:
                if dayDataList['person_id'] == personId:
                    if selfDay:
                        return "Cannot select two days of your own"
                    else:
                        day1Id = selected_days[1]
                        day2Id = selected_days[0]
                else:
                    if selfDay:
                        day2Id = selected_days[1]
                    else:
                        return "One of the days must be your own"

            if request.form.get("crisis"):
                cur.execute("INSERT INTO requests (day1, day2, crisis) VALUES (?,?,1)", (day1Id, day2Id))
            else:
                cur.execute("INSERT INTO requests (day1, day2, crisis) VALUES (?,?,0)", (day1Id, day2Id))

            con.commit()
            con.close()

            return "Something"
        else:
            con = sqlite3.connect("main.db")
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            
            if request.args.get("approve"):
                requestId = request.args.get("approve")
                if adminPerms == 1:
                    cur.execute("SELECT person_id from days WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,)) # TODO Swap crisis if it is crisis to swap
                    day1 = cur.fetchone()
                    day1Person = list(day1)
                    cur.execute("UPDATE days SET person_id = (SELECT person_id from days WHERE id = (SELECT day2 FROM requests WHERE id = ?)) WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,requestId))
                    cur.execute("UPDATE days SET person_id = ? WHERE id = (SELECT day2 FROM requests WHERE id = ?)", (day1Person[0],requestId))
                    cur.execute("UPDATE requests SET approved = 1, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                    con.commit()
                    cur.close()
                    return redirect("./account")
                else:
                    cur.execute("SELECT id FROM people WHERE id IN (SELECT person_id FROM days WHERE id IN (SELECT day2 FROM requests WHERE id = ?))", (requestId,))
                    row = cur.fetchone()
                    if row:
                        rowData = list(row)
                        if rowData[0] == personId:
                            cur.execute("SELECT person_id from days WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,)) # TODO Swap crisis if it is crisis to swap
                            day1 = cur.fetchone()
                            day1Person = list(day1)
                            cur.execute("UPDATE days SET person_id = (SELECT person_id from days WHERE id = (SELECT day2 FROM requests WHERE id = ?)) WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,requestId))
                            cur.execute("UPDATE days SET person_id = ? WHERE id = (SELECT day2 FROM requests WHERE id = ?)", (day1Person[0],requestId))
                            cur.execute("UPDATE requests SET approved = 1, approved_by = ?, timestamp = datetime() WHERE id = ?;", (personId, requestId))
                            con.commit()
                            cur.close()
                            return redirect("./account")
                        else:
                            attackDetails = "Thie could be someone trying a URL Injection attack. They have tried to approve a request where they do not have valid permissions to do so. User ID: " + personId + ", Request ID: " + requestId
                            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 1, ?)", (personId, attackDetails))
                            con.commit()
                            cur.close()
                            return "Something went wrong, Error: Could not confirm user permission. <a href='../'>Home</a>"
                    else:
                        cur.close()
                        return "Something went wrong, Error: Could not retrieve a person id from database" # TODO: log in database suspicious activity, possible URL injection attempt
            elif request.args.get("deny"):

                requestId = request.args.get("deny")
                if adminPerms == 1:
                    cur.execute("UPDATE requests SET approved = 2, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                    con.commit()
                    cur.close()
                    return redirect("./account")
                else:
                    cur.execute("SELECT id FROM people WHERE id IN (SELECT person_id FROM days WHERE id IN (SELECT day2 FROM requests WHERE id = ?))", (requestId,))
                    row = cur.fetchone()
                    if row:
                        rowData = list(row)
                        if rowData[0] == personId:
                            cur.execute("UPDATE requests SET approved = 2, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                            con.commit()
                            cur.close()
                            return redirect("./account")
                        else:
                            attackDetails = "Thie could be someone trying a URL Injection attack. They have tried to approve a request where they do not have valid permissions to do so. User ID: " + personId + ", Request ID: " + requestId
                            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 1, ?)", (personId, attackDetails))
                            con.commit()
                            cur.close()
                            return "Something went wrong, Error: Could not confirm user permission. <a href='../'>Home</a>"
                    else:
                        cur.close()
                        return "Something went wrong, Error: Could not retrieve a person id from database" # TODO: log in database suspicious activity, possible URL injection attempt

            if request.args.get("swap"):

                cur.execute("SELECT days.id, days.date, p1.name AS p1Name, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id LIMIT 25;")
                rows = cur.fetchall()
                daysData = [dict(row) for row in rows]

                con.close()

                return render_template("swap.html", days=daysData)
            
            cur.execute("SELECT requests.id, requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name FROM requests JOIN days d1 ON requests.day1 = d1.id JOIN days d2 ON requests.day2 = d2.id JOIN people ON d1.person_id = people.id WHERE day2 IN (SELECT id FROM days WHERE person_id = ? OR crisis_id = ?) AND approved = 0;", (personId, personId))
            rows = cur.fetchall()
            daysData = [dict(row) for row in rows]

            con.close()

            

            if adminPerms == 1:

                return render_template('admin.html', days=daysData)
            else:
                return render_template('user.html', days=daysData)
    else:
        return redirect("/")