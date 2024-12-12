from flask import Flask, render_template, url_for, request, redirect, session
from flask_session import Session
import sqlite3
import os
import json

app = Flask(__name__)

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

SETTINGS_FILE = "settings.json"

# TODO: Use appscheduler to run background processes
# TODO: A page for printing

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/", methods=["GET"])
def index():
    # Open a connection to the database
    con = sqlite3.connect("main.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Get all the names of people for the dropdown filter
    cur.execute("SELECT name FROM people;")
    rows = cur.fetchall()
    peopleData = [dict(row) for row in rows]

    if request.args.get('person'):
        person = request.args.get('person') # Filter days so that only the selected person shows
        cur.execute("SELECT days.date, p1.name AS oncall, p2.name AS crisis FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE days.person_id = ? OR days.crisis_id = ? ORDER BY days.id ASC LIMIT 50", (person,person))
    else: # Display all days with a limit of 50
        cur.execute("SELECT date, p1.name AS oncall, p2.name AS crisis FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id ORDER BY days.id ASC LIMIT 50")
    rows = cur.fetchall()
    daysData = [dict(row) for row in rows]

    con.close()

    # Render home page with data based on if user is signed in and admin or not
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
    if request.method == "POST": # If request is post someone has submitted the form
        if not request.form.get("password") or not request.form.get("name"): # Check if all fields have been filled
            # Report suspicious activity
            personId = 0
            con = sqlite3.connect("main.db")
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            attackDetails = "Thie could be someone trying to alter the client code to log in without required fields"
            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 2, ?)", (personId, attackDetails))
            con.commit()
            cur.close()
            return render_template('signin.html', accountLink="#", message="Not all fields were filled")
        
        enteredPassword = request.form.get("password")
        enteredName = request.form.get("name")

        # Open a connection with the database
        con = sqlite3.connect("main.db")
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Get all people with the given username and password
        cur.execute("SELECT id, name, password, admin FROM people WHERE name = ? AND password = ?;", (enteredName, enteredPassword))
        rows = cur.fetchall()
        if (len(rows) == 0): # If this is not an account let the user know
            return render_template('signin.html', accountLink="#", message="Incorrect Username or Password")
        peopleData = [dict(row) for row in rows]

        con.close()

        # Log in user with sessions
        session['user_id'] = peopleData[0]['id']
        session['name'] = peopleData[0]['name']
        session['password'] = peopleData[0]['password']
        session['admin'] = peopleData[0]['admin']

        return redirect("/")
        
    else: # If request is get then they haven't submitted a form
        return render_template('signin.html', accountLink="#")
    
@app.route("/account", methods=['GET', 'POST'])
def account():
    if session.get("admin") != None: # Check if a user is logged in
        adminPerms = session['admin']
        personId = session['user_id']

        if request.method == "POST":

            con = sqlite3.connect("main.db")
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            if request.form.get("swapRequest"): # Request for swap
                if not request.form.get("daySelect"):
                    return "Empty Field"
                
                selected_days = request.form.getlist('daySelect')
                if len(selected_days) != 2:
                    return "Wrong number of days selected"

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

                cur.execute("SELECT days.id, days.date, p1.name AS p1Name, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id LIMIT 50;")
                rows = cur.fetchall()
                daysData = [dict(row) for row in rows]

                if request.form.get("crisis"):
                    if dayDataList['crisis_id'] == personId:
                        if selfDay:
                            con.close()
                            if adminPerms == 1:
                                return render_template("swap.html", days=daysData, controlText="Admin", controlLink="./account", warn="Cannot select two days of your own")
                            else:
                                return render_template("swap.html", days=daysData, controlText="Swap", controlLink="./account", warn="Cannot select two days of your own")
                        else:
                            day1Id = selected_days[1]
                            day2Id = selected_days[0]
                    else:
                        if selfDay:
                            day2Id = selected_days[1]
                        else:
                            con.close()
                            if adminPerms == 1:
                                return render_template("swap.html", days=daysData, controlText="Admin", controlLink="./account", warn="One of the days must be your own")
                            else:
                                return render_template("swap.html", days=daysData, controlText="Swap", controlLink="./account", warn="One of the days must be your own")
                else:
                    if dayDataList['person_id'] == personId:
                        if selfDay:
                            con.close()
                            if adminPerms == 1:
                                return render_template("swap.html", days=daysData, controlText="Admin", controlLink="./account", warn="Cannot select two days of your own")
                            else:
                                return render_template("swap.html", days=daysData, controlText="Swap", controlLink="./account", warn="Cannot select two days of your own")
                        else:
                            day1Id = selected_days[1]
                            day2Id = selected_days[0]
                    else:
                        if selfDay:
                            day2Id = selected_days[1]
                        else:
                            con.close()
                            if adminPerms == 1:
                                return render_template("swap.html", days=daysData, controlText="Admin", controlLink="./account", warn="One of the days must be your own")
                            else:
                                return render_template("swap.html", days=daysData, controlText="Swap", controlLink="./account", warn="One of the days must be your own")

                if request.form.get("crisis"):
                    cur.execute("INSERT INTO requests (day1, day2, crisis) VALUES (?,?,1)", (day1Id, day2Id))
                else:
                    cur.execute("INSERT INTO requests (day1, day2, crisis) VALUES (?,?,0)", (day1Id, day2Id))

                con.commit()
                con.close()

                return redirect("./account")
            elif request.form.get("approveSwap"): # Approve a swap
                if not request.form.get("id"):
                    return "Something went wrong"
                requestId = request.form.get("id")
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
                        attackDetails = "Thie could be someone trying a URL Injection attack. They have tried to approve a request that does not exist. User ID: " + personId + ", Request ID: " + requestId
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 1, ?)", (personId, attackDetails))
                        con.commit()
                        cur.close()
                        return "Something went wrong, Error: Could not retrieve a person id from database"
            elif request.form.get("denySwap"): # Deny a swap
                if not request.form.get("id"):
                    return "Something went wrong" # Redirect
                requestId = request.args.get("id")
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
                        attackDetails = "Thie could be someone trying a URL Injection attack. They have tried to approve a request that does not exist. User ID: " + personId + ", Request ID: " + requestId
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 1, ?)", (personId, attackDetails))
                        con.commit()
                        return "Something went wrong, Error: Could not retrieve a person id from database"
            elif request.form.get("updateWeeks"):
                weeks = request.form.get("weeks")
                data = {"weeks": weeks}
                json_object = json.dumps(data, indent=4)
                with open(SETTINGS_FILE, 'w') as file:
                    file.write(json_object)
                return redirect("./account")

            return "Something went wrong, unknown post request"
        else:
            con = sqlite3.connect("main.db")
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            if request.args.get("swap"): # Display page for person requesting to make a new swap

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.name AS p1Name, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id LIMIT 50;")
                rows = cur.fetchall()
                daysData = [dict(row) for row in rows]

                con.close()

                if adminPerms == 1:
                    return render_template("swap.html", days=daysData, controlText="Admin", controlLink="./account")
                else:
                    return render_template("swap.html", days=daysData, controlText="Swap", controlLink="./account")
            
            # Get information of all pending swaps user has to approve
            cur.execute("SELECT requests.id, requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name FROM requests JOIN days d1 ON requests.day1 = d1.id JOIN days d2 ON requests.day2 = d2.id JOIN people ON d1.person_id = people.id WHERE day2 IN (SELECT id FROM days WHERE person_id = ? OR crisis_id = ?) AND (approved IS NULL OR approved NOT IN (1,2));", (personId, personId))
            rows = cur.fetchall()
            daysData = [dict(row) for row in rows]

            if adminPerms == 1:
                # Get information for extra tables on admin page
                if request.args.get("pending"):
                    cur.execute("SELECT requests.id, requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name FROM requests JOIN days d1 ON requests.day1 = d1.id JOIN days d2 ON requests.day2 = d2.id JOIN people ON d1.person_id = people.id WHERE (approved IS NULL OR approved NOT IN (1,2));")
                    rows = cur.fetchall()
                    pendingData = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, pendingSwaps=pendingData)
                elif request.args.get("suspicious"):
                    cur.execute("SELECT suspicious.type, suspicious.details, suspicious.timestamp, people.name FROM suspicious LEFT JOIN people ON suspicious.person_id = people.id LIMIT 25;")
                    rows = cur.fetchall()
                    suspiciousData = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, suspicious=suspiciousData)
                elif request.args.get("swapHistory"):
                    cur.execute("SELECT requests.id, requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name, requests.approved, requests.timestamp FROM requests JOIN days d1 ON requests.day1 = d1.id JOIN days d2 ON requests.day2 = d2.id JOIN people ON d1.person_id = people.id WHERE approved IN (1,2);")
                    rows = cur.fetchall()
                    swapHistory = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, swapHistory=swapHistory)
                elif request.args.get("oncallHistory"):
                    cur.execute("SELECT days.date, p1.name AS person1, p2.name AS person2 FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE completed = 1 LIMIT 25;")
                    rows = cur.fetchall()
                    oncallHistory = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, oncallHistory=oncallHistory)
                elif request.args.get("users"):
                    cur.execute("SELECT * FROM people ORDER BY admin DESC;")
                    rows = cur.fetchall()
                    userData = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, users=userData)
                elif request.args.get("settings"):
                    settings = {"weeks": 0}
                    if os.path.isfile(SETTINGS_FILE):
                        with open(SETTINGS_FILE, 'r') as file:
                            data = json.load(file)
                        settings = data
                        
                    return render_template("admin.html", days=daysData, settings=settings)

                con.close()
                return render_template('admin.html', days=daysData)
            else:
                con.close()
                return render_template('user.html', days=daysData)
    else:
        return redirect("/")
    
@app.route("/editUser", methods=['GET', 'POST'])
def editUser():
    con = sqlite3.connect("main.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if request.method == "POST":
        # Check all the fields have been filled
        if not request.form.get("name") or not request.form.get("password") or not request.form.get("email") or not request.form.get("number") or not request.form.get("weight"):
            
            

            attackDetails = "Thie could be someone trying to alter the client code to complete the update user form without filling all fields"
            personId = session['user_id']
            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 2, ?)", (personId, attackDetails))
            con.commit()
            cur.close()
            return render_template('editUser.html', user=userData, sessionData=sessionData, warn="Not all fields were filled")
        
        # Get information from filled fields
        if not request.form.get("new") and request.form.get("id"):        
            userId = request.form.get("id")
        elif not request.form.get("new") and not request.form.get("id"):
            cur.execute("SELECT * FROM people WHERE id = ?;", (person_id,))
            row = cur.fetchone()
            userData = dict(row)
            attackDetails = "Thie could be someone trying to alter the client code to complete the update user form without filling all fields"
            personId = session['user_id']
            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 2, ?)", (personId, attackDetails))
            con.commit()
            cur.close()
            return render_template('editUser.html', user=userData, sessionData=sessionData, warn="Not all fields were filled")
        name = request.form.get("name")
        password = request.form.get("password")
        email = request.form.get("email")
        number = request.form.get("number")
        sessions = request.form.getlist("sessions")
        weight = int(request.form.get("weight"))
        weightAdd = 0
        admin = 0
        sessionsNumber = 0
        
        # Check if the weight checkbox is checked
        if request.form.get("updateWeight"):
            weight = 0
            weightAdd = 1

        if request.form.get("admin"):
            admin = 1

        # Calculate weight for user
        for i in range(len(sessions)):
            sessionsNumber += int(sessions[i])
            weight += weightAdd

        if request.form.get("new"): # Create new user
            cur.execute("INSERT INTO people (name, password, email, number, sessions, weight, admin, diff, end_diff) VALUES (?,?,?,?,?,?,?,0,0)", (name, password, email, number, sessionsNumber, weight, admin))
        else: # Edit user
            cur.execute("UPDATE people SET name = ?, password = ?, email = ?, number = ?, sessions = ?, weight = ?, admin = ? WHERE id = ?", (name, password, email, number, sessionsNumber, weight, admin, userId))

        con.commit()
        con.close()

        return redirect("./account?users=1")
    else:
        person_id = request.args.get("id")
        if person_id: # Check if fields are filled
            person_id = int(person_id)
            userData = 0
            sessionData = 0

            # Check if there is a user to edit
            if person_id != 0:
                # Select information about user to edit
                cur.execute("SELECT * FROM people WHERE id = ?;", (person_id,))
                row = cur.fetchone()
                userData = dict(row)
                con.close()

                sessionsNumber = userData['sessions']
                sessionData = {}
                daysValues = {"fa": 512, "fm": 256, "tha": 128, "thm": 64, "wa": 32, "wm": 16, "ta": 8, "tm": 4, "ma": 2, "mm": 1}

                # Find the sessions the person works based on their session value
                if sessionsNumber:
                    for key in daysValues.keys():
                        if sessionsNumber >= daysValues[key]:
                            sessionsNumber -= daysValues[key]
                            sessionData[key] = "Checked"
                        else:
                            sessionData[key] = ""

            return render_template('editUser.html', user=userData, sessionData=sessionData)
        else:
            return redirect("./account")