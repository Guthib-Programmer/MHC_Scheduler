from flask import Flask, render_template, url_for, request, redirect, session
from flask_session import Session
from flask_apscheduler import APScheduler
from collections import deque
from operator import itemgetter
import sqlite3
import os
import json
from datetime import timedelta
from datetime import datetime
from datetime import time
import holidays

app = Flask(__name__)

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

SETTINGS_FILE = "settings.json"

class Config:
    SCHEDULER_API_ENABLED = True

scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# TODO: Mark past days as completed

def format_date(date_str):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%a %d %B %Y")

@scheduler.task('cron', id='assignOncall', week='*', day_of_week="mon", hour=8, minute=59)
def assignOncall():

    # Open a connection to the database
    con = sqlite3.connect("main.db")
    con.row_factory = lambda cursor, row: row[0]
    listCur = con.cursor()
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    listCur.execute("SELECT date FROM days ORDER BY id DESC LIMIT 1;")
    datesData = listCur.fetchall()

    settings = {"weeks": 0}
    if os.path.isfile(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as file:
            data = json.load(file)
        settings = data

    days_to_plan = int(settings['weeks']) * 7
    weeks_ahead = timedelta(days=days_to_plan)
    dt = datetime.now()
    cut_off_date = (dt + weeks_ahead).date()

    datesData = [datetime.strptime(day, "%Y-%m-%d").date() for day in datesData]

    if len(datesData) < 1:
        datesData.append(datetime.strptime(datetime.today().strftime("%Y-%m-%d"), "%Y-%m-%d").date())

    if cut_off_date > datesData[0]:
        print("Asigning days")
        
        # Get a list of people and their diff counts
        cur.execute("SELECT id, diff, end_diff, weight, active, activate_date FROM people;")
        rows = cur.fetchall()
        peopleData = [dict(row) for row in rows]

        cur.execute("SELECT date, crisis_id, person_id FROM days ORDER BY id DESC LIMIT 7;")
        rows = cur.fetchall()
        previousDaysData = [dict(row) for row in rows]

        if len(previousDaysData) > 0:
            crisisId = int(previousDaysData[0]['crisis_id'])
        else:
            crisisId = peopleData[0]['id']

        previousDaysData.reverse()
        peopleThisWeek = []

        for day in previousDaysData:
            day['date'] = datetime.strptime(day['date'], "%Y-%m-%d")
            if day['date'].weekday == 0:
                peopleThisWeek = []
            else:
                peopleThisWeek.append(day['person_id'])
                print("")

        while cut_off_date > datesData[0]:

            date = datesData[0]
            newDate = date + timedelta(days=1)
            weekday = newDate.weekday()
            isWeekend = False

            for personOffset in range(len(peopleData)):
                person = peopleData[personOffset]
                if person['active']:
                    if person['activate_date']:
                        if datetime.strptime(person['activate_date'], "%Y-%m-%d").date() < newDate:
                            cur.execute("UPDATE people SET active = 0, activate_date = NULL WHERE id = ?", (person['id'],))
                            peopleData[personOffset]['active'] = 0
                            peopleData[personOffset]['activate_date'] = None
                            con.commit()
                else:
                    if person['finish_date']:
                        if datetime.strptime(person['finish_date'], "%Y-%m-%d").date() < newDate:
                            listCur.execute("SELECT diff FROM people ORDER BY diff DESC LIMIT 1")
                            highestDiff = listCur.fetchall()
                            listCur.execute("SELECT end_diff FROM people ORDER BY end_diff DESC LIMIT 1")
                            highestEndDiff = listCur.fetchall()
                            cur.execute("UPDATE people SET active = 1, activate_date = NULL, diff = ?, end_diff = ? WHERE id = ?", (highestDiff[0], highestEndDiff[0], person['id']))
                            peopleData[personOffset]['active'] = 1
                            peopleData[personOffset]['activate_date'] = None
                            peopleData[personOffset]['diff'] = highestDiff[0]
                            peopleData[personOffset]['end_diff'] = highestEndDiff[0]
                            con.commit()

            nz_holidays = holidays.country_holidays('NZ', subdiv='OTA')
            if newDate in nz_holidays:
                cur.execute("INSERT INTO days (person_id, date, crisis_id, completed) VALUES (-1,?,?,0)", (newDate, crisisId))
                con.commit()
                datesData = deque(datesData)
                datesData.appendleft(newDate)
                datesData = list(datesData)
                continue

            if weekday in [5,6]:
                peopleData = sorted(peopleData, key=itemgetter('end_diff'))
                isWeekend = True
            else:
                peopleData = sorted(peopleData, key=itemgetter('diff'))

            if weekday == 0:
                peopleThisWeek = []

            cur.execute("SELECT COUNT(*) FROM people;")
            rows = cur.fetchone()
            count = list(rows)[0]

            if count <= len(peopleThisWeek) + 1:
                peopleThisWeek = []

            if weekday == 6:
                while True:
                    crisisId += 1
                    if not any(d['id'] == crisisId for d in peopleData):
                        crisisId = 1
                    while not any(d['id'] == crisisId for d in peopleData):
                        crisisId += 1
                    cur.execute("SELECT finish_date, active FROM people WHERE id = ?", (crisisId,))
                    row = cur.fetchone()
                    person_finish = dict(row)['finish_date']
                    active = dict(row)['active']
                    if active == 1:
                        if person_finish != None:
                            finish_date = datetime.strptime(person_finish, "%Y-%m-%d").date()
                            week_ahead = timedelta(days=7)
                            dt = datetime.now()
                            cut_off_date_oncall = (dt + week_ahead).date()

                            if finish_date > cut_off_date_oncall:
                                break
                        else:
                            break

            for personOffset in range(len(peopleData)):

                # Check if person is eligible for day
                person = peopleData[personOffset]

                person_is_eligible = False
                if person['id'] != crisisId:
                    if person['id'] not in peopleThisWeek:
                        if person['active'] == 1:
                            person_is_eligible = True

                if person_is_eligible:

                    # Assign day to person
                    cur.execute("INSERT INTO days (person_id, date, crisis_id, completed) VALUES (?,?,?,0)", (person['id'], newDate, crisisId))
                    peopleThisWeek.append(person['id'])

                    if isWeekend:
                        newDiff = round(person['end_diff'] + (100 / person['weight']))
                        peopleData[personOffset]['end_diff'] = newDiff
                        cur.execute("UPDATE people SET end_diff = ? WHERE id = ?", (newDiff, person['id']))
                    else:
                        newDiff = round(person['diff'] + (100 / person['weight']))
                        peopleData[personOffset]['diff'] = newDiff
                        cur.execute("UPDATE people SET diff = ? WHERE id = ?", (newDiff, person['id']))
                    
                    con.commit()

                    datesData = deque(datesData)
                    datesData.appendleft(newDate)
                    datesData = list(datesData)
                    break
        
        print("Finished")      
    con.close()

# TODO: Message users of their oncalls
@scheduler.task('cron', id='messageUser', day_of_week='*', hour=9, minute=0)
def messageUser():
    print("Messaging user")

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
    cur.execute("SELECT name, id FROM people;")
    rows = cur.fetchall()
    peopleData = [dict(row) for row in rows]

    if request.args.get('person'):
        person = request.args.get('person') # Filter days so that only the selected person shows
        cur.execute("SELECT days.date, p1.id AS oncallId, p1.name AS oncall, p1.color AS oncallColor, p2.name AS crisis, p2.color AS crisisColor FROM days LEFT JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE (days.person_id = ? OR days.crisis_id = ?) AND days.completed = 0 ORDER BY days.id ASC LIMIT 50", (person,person))
    else: # Display all days with a limit of 50
        cur.execute("SELECT date, p1.id AS oncallId, p1.name AS oncall, p1.color AS oncallColor, p2.name AS crisis, p2.color AS crisisColor FROM days LEFT JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id AND days.completed = 0 ORDER BY days.id ASC LIMIT 50")
    rows = cur.fetchall()
    daysData = [dict(row) for row in rows]
    for day in daysData:
        day['date'] = format_date(day['date'])

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
            con.row_factory = lambda cursor, row: row[0]
            listCur = con.cursor()

            if request.form.get("swapRequest"): # Request for swap

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p1.id = ? LIMIT 50;", (personId,))
                rows = cur.fetchall()
                selfOncallData = [dict(row) for row in rows]
                for day in selfOncallData:
                    day['date'] = format_date(day['date'])

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p1.id != ? AND p2.id != ? LIMIT 50;", (personId, personId))
                rows = cur.fetchall()
                otherOncallData = [dict(row) for row in rows]
                for day in otherOncallData:
                    day['date'] = format_date(day['date'])

                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p2.id = ? LIMIT 50;", (personId,))
                rows = cur.fetchall()
                selfCrisisData = [dict(row) for row in rows]
                for day in selfCrisisData:
                    day['date'] = format_date(day['date'])

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p2.id != ? AND p2.id != ? LIMIT 50;", (personId, personId))
                rows = cur.fetchall()
                otherCrisisData = [dict(row) for row in rows]
                for day in otherCrisisData:
                    day['date'] = format_date(day['date'])


                if request.form.get("crisis"):
                    if not request.form.get("ownCrisis") or not request.form.get("otherCrisis"):
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where one of the days is missing."
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        if adminPerms == 1:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                        else:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")
                    
                    firstDay = request.form.get("ownCrisis")
                    secondDay = request.form.get("otherCrisis")        
                else:
                    if not request.form.get("ownOncall") or not request.form.get("otherOncall"):
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where one of the days is missing."
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        if adminPerms == 1:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                        else:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")
                    
                    firstDay =  request.form.get("ownOncall")
                    secondDay = request.form.get("otherOncall")

                cur.execute("SELECT * FROM days WHERE id = ?", (firstDay,))
                dayData = cur.fetchone()
                day1DataList = dict(dayData)

                cur.execute("SELECT * FROM days WHERE id = ?", (secondDay,))
                dayData = cur.fetchone()
                day2DataList = dict(dayData)

                if day1DataList['completed'] == 1 or day2DataList['completed'] == 1:
                    attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where one of the days has already been completed."
                    cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                    if adminPerms == 1:
                        return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                    else:
                        return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")
                
                if day1DataList['person_id'] == day2DataList['crisis_id'] or day1DataList['crisis_id'] == day2DataList['person_id']:
                    attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap that would result in someone having both oncall and crisis on the same day."
                    cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                    if adminPerms == 1:
                        return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                    else:
                        return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")

                listCur.execute("SELECT day1 FROM requests WHERE approved = 0 OR approved IS NULL")
                day1Ids = listCur.fetchall()

                listCur.execute("SELECT day2 FROM requests WHERE approved = 0 OR approved IS NULL")
                day2Ids = listCur.fetchall()

                dayIds = day1Ids + day2Ids
                
                if firstDay in dayIds or secondDay in dayIds:
                    attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap that would result in someone having both oncall and crisis on the same day."
                    cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                    if adminPerms == 1:
                        return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                    else:
                        return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")

                cur.execute("SELECT days.id, days.date, p1.name AS p1Name, p2.name AS p2Name FROM days LEFT JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id LIMIT 50;")
                rows = cur.fetchall()
                daysData = [dict(row) for row in rows]

                selfDay = False
                day1Id = 0
                day2Id = 0
                requested_id = 0

                if request.form.get("crisis"):
                    if day1DataList['crisis_id'] == personId and day2DataList['crisis_id'] == personId:
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where both days are their own."
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        if adminPerms == 1:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                        else:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")
                    elif day1DataList['crisis_id'] == personId:
                        day1Id = firstDay
                        day2Id = secondDay
                    elif day2DataList['crisis_id'] == personId:
                        day1Id = secondDay
                        day2Id = firstDay
                    else:
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where both days are other people's."
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        if adminPerms == 1:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                        else:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")

                    cur.execute("INSERT INTO requests (day1, day2, crisis, requested_id, requested_by) VALUES (?,?,1,?,?)", (day1Id, day2Id, requested_id, personId))
                else:
                    if day1DataList['person_id'] == personId and day2DataList['person_id'] == personId:
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where both days are their own."
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        if adminPerms == 1:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                        else:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")

                    elif day1DataList['person_id'] == personId:
                        day1Id = firstDay
                        day2Id = secondDay
                    elif day2DataList['person_id'] == personId:
                        day1Id = secondDay
                        day2Id = firstDay
                    else:
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to request a swap where both days are other people's."
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        if adminPerms == 1:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account", warn="Something went wrong, please try again")
                        else:
                            return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account", warn="Something went wrong, please try again")

                    cur.execute("INSERT INTO requests (day1, day2, crisis, requested_id, requested_by) VALUES (?,?,0,?,?)", (day1Id, day2Id, requested_id, personId))
                
                con.commit()

                # TODO: Send a message to the person who is being requested to swap
                
                return redirect("./account?success=1")

            elif request.form.get("approveSwap"): # Approve a swap
                if not request.form.get("id"):
                    return "Something went wrong"
                requestId = request.form.get("id")

                cur.execute("SELECT crisis FROM requests WHERE id = ?", (requestId,))
                crisisResult = cur.fetchone()
                crisis = list(crisisResult)[0]

                if adminPerms == 1:
                    if crisis == 1:
                        cur.execute("SELECT crisis_id from days WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,))
                        day1 = cur.fetchone()
                        day1Person = list(day1)
                        cur.execute("UPDATE days SET crisis_id = (SELECT crisis_id from days WHERE id = (SELECT day2 FROM requests WHERE id = ?)) WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,requestId))
                        cur.execute("UPDATE days SET crisis_id = ? WHERE id = (SELECT day2 FROM requests WHERE id = ?)", (day1Person[0],requestId))
                        cur.execute("UPDATE requests SET approved = 1, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                        con.commit()
                        cur.close()
                    else:
                        cur.execute("SELECT person_id from days WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,))
                        day1 = cur.fetchone()
                        day1Person = list(day1)
                        cur.execute("UPDATE days SET person_id = (SELECT person_id from days WHERE id = (SELECT day2 FROM requests WHERE id = ?)) WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,requestId))
                        cur.execute("UPDATE days SET person_id = ? WHERE id = (SELECT day2 FROM requests WHERE id = ?)", (day1Person[0],requestId))
                        cur.execute("UPDATE requests SET approved = 1, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                        con.commit()
                        cur.close()
                    return redirect("./account?pending=1")
                else:
                    cur.execute("SELECT id FROM people WHERE id IN (SELECT person_id FROM days WHERE id IN (SELECT day2 FROM requests WHERE id = ?))", (requestId,))
                    row = cur.fetchone()
                    if row:
                        rowData = list(row)
                        if rowData[0] == personId:
                            if crisis == 1:
                                cur.execute("SELECT crisis_id from days WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,))
                                day1 = cur.fetchone()
                                day1Person = list(day1)
                                cur.execute("UPDATE days SET crisis_id = (SELECT crisis_id from days WHERE id = (SELECT day2 FROM requests WHERE id = ?)) WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,requestId))
                                cur.execute("UPDATE days SET crisis_id = ? WHERE id = (SELECT day2 FROM requests WHERE id = ?)", (day1Person[0],requestId))
                                cur.execute("UPDATE requests SET approved = 1, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                                con.commit()
                                cur.close()
                            else:
                                cur.execute("SELECT person_id from days WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,))
                                day1 = cur.fetchone()
                                day1Person = list(day1)
                                cur.execute("UPDATE days SET person_id = (SELECT person_id from days WHERE id = (SELECT day2 FROM requests WHERE id = ?)) WHERE id = (SELECT day1 FROM requests WHERE id = ?)", (requestId,requestId))
                                cur.execute("UPDATE days SET person_id = ? WHERE id = (SELECT day2 FROM requests WHERE id = ?)", (day1Person[0],requestId))
                                cur.execute("UPDATE requests SET approved = 1, approved_by = ?, timestamp = datetime() WHERE id = ?;", (personId, requestId))
                                con.commit()
                                cur.close()
                            return redirect("./account")
                        else:
                            attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to approve a swap request where they do not have valid permissions to do so. User ID: " + personId + ", Request ID: " + requestId
                            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                            con.commit()
                            cur.close()
                            return "Something went wrong, Error: Could not confirm user permission. <a href='../'>Home</a>"
                    else:
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to approve a swap request that does not exist. User ID: " + personId + ", Request ID: " + requestId
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        con.commit()
                        cur.close()
                        return "Something went wrong, Error: Could not retrieve a person id from database"
            elif request.form.get("denySwap"): # Deny a swap
                if not request.form.get("id"):
                    return "Something went wrong" # Redirect
                requestId = request.form.get("id")
                if adminPerms == 1:
                    cur.execute("UPDATE requests SET approved = 2, approved_by = ?, timestamp = datetime() WHERE id = ?", (personId, requestId))
                    con.commit()
                    cur.close()
                    return redirect("./account?pending=1")
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
                            attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to deny a request where they do not have valid permissions to do so. User ID: " + personId + ", Request ID: " + requestId
                            cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                            con.commit()
                            cur.close()
                            return "Something went wrong, Error: Could not confirm user permission. <a href='../'>Home</a>"
                    else:
                        cur.close()
                        attackDetails = "Thie could be someone trying a foreign post request attack or client code manipulation. They have tried to deny a request that does not exist. User ID: " + personId + ", Request ID: " + requestId
                        cur.execute("INSERT INTO suspicious (person_id, timestamp, type, details) VALUES (?, datetime(), 3, ?)", (personId, attackDetails))
                        con.commit()
                        return "Something went wrong, Error: Could not retrieve a person id from database"
            elif request.form.get("updateWeeks") and adminPerms == 1:
                weeks = int(request.form.get("weeks"))
                data = {"weeks": weeks}
                json_object = json.dumps(data, indent=4)

                # Open the settings file and read the current number of weeks
                with open(SETTINGS_FILE, 'r') as file:
                    current_settings = json.load(file)
                current_weeks = current_settings.get("weeks", 0)

                with open(SETTINGS_FILE, 'w') as file:
                    file.write(json_object)

                # If the updated number of weeks is less than the current number of weeks
                if weeks < current_weeks:
                    # Calculate the cut-off date
                    cut_off_date = datetime.now().date() + timedelta(days=weeks * 7)
                    cut_off_date_str = cut_off_date.strftime("%Y-%m-%d")

                    print(f"Cut off date: {cut_off_date_str}")

                    # Delete days in the database that are beyond the updated number of weeks
                    cur.execute("DELETE FROM days WHERE date > ?", (cut_off_date_str,))
                    con.commit()
                else:
                    assignOncall()

                return redirect("./account")
            elif request.form.get("volunteer"):
                dayId = request.form.get("id")
                cur.execute("UPDATE days SET person_id = ? WHERE id = ?", (personId, dayId))
                con.commit()
                con.close()
                return redirect("./account")

            return "Something went wrong, unknown post request"
        else:
            con = sqlite3.connect("main.db")
            con.row_factory = sqlite3.Row
            cur = con.cursor()

            if request.args.get("swap"): # Display page for person requesting to make a new swap

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p1.id = ? AND days.id NOT IN (SELECT day1 FROM requests WHERE approved = 0 OR approved IS NULL) AND days.id NOT IN (SELECT day2 FROM requests WHERE approved = 0 OR approved IS NULL) LIMIT 50;", (personId,))
                rows = cur.fetchall()
                selfOncallData = [dict(row) for row in rows]
                for day in selfOncallData:
                    day['date'] = format_date(day['date'])

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p1.id != ? AND p2.id != ? AND days.id NOT IN (SELECT day1 FROM requests WHERE approved = 0 OR approved IS NULL) AND days.id NOT IN (SELECT day2 FROM requests WHERE approved = 0 OR approved IS NULL) LIMIT 50;", (personId, personId))
                rows = cur.fetchall()
                otherOncallData = [dict(row) for row in rows]
                for day in otherOncallData:
                    day['date'] = format_date(day['date'])

                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p2.id = ? AND days.id NOT IN (SELECT day1 FROM requests WHERE approved = 0 OR approved IS NULL) AND days.id NOT IN (SELECT day2 FROM requests WHERE approved = 0 OR approved IS NULL) LIMIT 50;", (personId,))
                rows = cur.fetchall()
                selfCrisisData = [dict(row) for row in rows]
                for day in selfCrisisData:
                    day['date'] = format_date(day['date'])

                # Get information of days
                cur.execute("SELECT days.id, days.date, p1.id AS p1id, p1.name AS p1Name, p2.id AS p2id, p2.name AS p2Name FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE p2.id != ? AND p2.id != ? AND days.id NOT IN (SELECT day1 FROM requests WHERE approved = 0 OR approved IS NULL) AND days.id NOT IN (SELECT day2 FROM requests WHERE approved = 0 OR approved IS NULL) LIMIT 50;", (personId, personId))
                rows = cur.fetchall()
                otherCrisisData = [dict(row) for row in rows]
                for day in otherCrisisData:
                    day['date'] = format_date(day['date'])

                con.close()

                if adminPerms == 1:
                    return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Admin", controlLink="./account")
                else:
                    return render_template("swap.html", selfOncall=selfOncallData, otherOncall=otherOncallData, selfCrisis=selfCrisisData, otherCrisis=otherCrisisData, controlText="Swap", controlLink="./account")
            
            # Get information of all pending swaps user has to approve
            cur.execute("SELECT requests.id, requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name FROM requests JOIN days d1 ON requests.day1 = d1.id JOIN days d2 ON requests.day2 = d2.id JOIN people ON d1.person_id = people.id WHERE requests.day2 IN (SELECT id FROM days WHERE person_id = ? OR crisis_id = ?) AND (approved IS NULL OR approved NOT IN (1,2));", (personId, personId))
            rows = cur.fetchall()
            daysData = [dict(row) for row in rows]
            for day in daysData:
                day['day1Name'] = format_date(day['day1Name'])
                day['day2Name'] = format_date(day['day2Name'])

            cur.execute("SELECT * FROM days WHERE person_id = -1")
            rows = cur.fetchall()
            volunteerDays = [dict(row) for row in rows]
            for day in volunteerDays:
                day['date'] = format_date(day['date'])

            if adminPerms == 1:
                # Get information for extra tables on admin page
                if request.args.get("pending"):
                    cur.execute("SELECT requests.id, requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name FROM requests JOIN days d1 ON requests.day1 = d1.id JOIN days d2 ON requests.day2 = d2.id JOIN people ON d1.person_id = people.id WHERE (approved IS NULL OR approved NOT IN (1,2));")
                    rows = cur.fetchall()
                    pendingData = [dict(row) for row in rows]
                    for day in pendingData:
                        day['day1Name'] = format_date(day['day1Name'])
                        day['day2Name'] = format_date(day['day2Name'])
                    con.close()
                    return render_template('admin.html', days=daysData, pendingSwaps=pendingData, volunteerDays=volunteerDays)
                elif request.args.get("suspicious"):
                    cur.execute("SELECT suspicious.type, suspicious.details, suspicious.timestamp, people.name FROM suspicious LEFT JOIN people ON suspicious.person_id = people.id ORDER BY suspicious.id DESC LIMIT 25;")
                    rows = cur.fetchall()
                    suspiciousData = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, suspicious=suspiciousData, volunteerDays=volunteerDays)
                elif request.args.get("swapHistory"):
                    cur.execute("""SELECT requests.crisis, d1.date AS day1Name, d2.date AS day2Name, people.name, requests.approved, requests.timestamp, p1.name AS name2, p2.name AS name3 
                                    FROM requests 
                                    JOIN days d1 ON requests.day1 = d1.id 
                                    JOIN days d2 ON requests.day2 = d2.id 
                                    JOIN people ON requests.requested_by = people.id 
                                    JOIN people p1 ON requests.requested_id = p1.id
                                    JOIN people p2 ON requests.approved_by = p2.id
                                    WHERE approved IN (1,2) ORDER BY requests.id DESC LIMIT 50;""")
                    rows = cur.fetchall()
                    swapHistory = [dict(row) for row in rows]
                    for day in swapHistory:
                        day['day1Name'] = format_date(day['day1Name'])
                        day['day2Name'] = format_date(day['day2Name'])
                    con.close()
                    return render_template('admin.html', days=daysData, swapHistory=swapHistory, volunteerDays=volunteerDays)
                elif request.args.get("oncallHistory"):
                    cur.execute("SELECT days.date, p1.name AS person1, p2.name AS person2 FROM days JOIN people p1 ON days.person_id = p1.id JOIN people p2 ON days.crisis_id = p2.id WHERE completed = 1 ORDER BY days.id DESC LIMIT 25;")
                    rows = cur.fetchall()
                    oncallHistory = [dict(row) for row in rows]
                    for day in oncallHistory:
                        day['date'] = format_date(day['date'])
                    con.close()
                    return render_template('admin.html', days=daysData, oncallHistory=oncallHistory, volunteerDays=volunteerDays)
                elif request.args.get("users"):
                    cur.execute("SELECT * FROM people ORDER BY admin DESC;")
                    rows = cur.fetchall()
                    userData = [dict(row) for row in rows]
                    con.close()
                    return render_template('admin.html', days=daysData, users=userData, volunteerDays=volunteerDays)
                elif request.args.get("settings"):
                    settings = {"weeks": 0}
                    if os.path.isfile(SETTINGS_FILE):
                        with open(SETTINGS_FILE, 'r') as file:
                            data = json.load(file)
                        settings = data
                        
                    return render_template("admin.html", days=daysData, settings=settings, volunteerDays=volunteerDays)
                elif request.args.get("success"):
                    success_message = request.args.get("success")
                    if success_message == '1' or success_message == 1:
                        con.close()
                        return render_template("admin.html", days=daysData, volunteerDays=volunteerDays, success="You have successfully requested a swap. Contact an admin if this needs to be undone.")

                con.close()
                return render_template('admin.html', days=daysData, volunteerDays=volunteerDays)
            else:
                con.close()

                if request.args.get("success"):
                    success_message = request.args.get("success")
                    if success_message == '1' or success_message == 1:
                        return render_template("admin.html", days=daysData, volunteerDays=volunteerDays, success="You have successfully requested a swap. Contact an admin if this needs to be undone.")

                return render_template('user.html', days=daysData, volunteerDays=volunteerDays)
    else:
        return redirect("/")
    
@app.route("/editUser", methods=['GET', 'POST'])
def editUser():
    con = sqlite3.connect("main.db")
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if request.method == "POST":
        # Check all the fields have been filled
        if not request.form.get("start") or not request.form.get("name") or not request.form.get("password") or not request.form.get("email") or not request.form.get("number") or not request.form.get("weight") or not request.form.get("color"):
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
        color = request.form.get("color")
        start = request.form.get("start")
        weightAdd = 0
        admin = 0
        sessionsNumber = 0
        
        # Check if the weight checkbox is checked
        if request.form.get("updateWeight"):
            weight = 0
            weightAdd = 1

        if request.form.get("admin"):
            admin = 1

        if request.form.get("endDateCheck"):
            endDate = request.form.get("endDate")
        else:
            endDate = None

        if start == "date":
            active = 0
            startDate = request.form.get("startDate")
        else:
            active = 1
            startDate = None

        # Calculate weight for user
        for i in range(len(sessions)):
            sessionsNumber += int(sessions[i])
            weight += weightAdd

        if request.form.get("new"): # Create new user
            con.row_factory = lambda cursor, row: row[0]
            listCur = con.cursor()
            listCur.execute("SELECT diff FROM people ORDER BY diff DESC LIMIT 1")
            highestDiff = listCur.fetchall()
            listCur.execute("SELECT end_diff FROM people ORDER BY end_diff DESC LIMIT 1")
            highestEndDiff = listCur.fetchall()
            cur.execute("INSERT INTO people (name, password, email, number, sessions, weight, admin, diff, end_diff, color, finish_date, active, activate_date, diff, end_diff) VALUES (?,?,?,?,?,?,?,0,0,?,?,?,?,?,?)", (name, password, email, number, sessionsNumber, weight, admin, color, endDate, active, startDate, highestDiff, highestEndDiff))
        else: # Edit user
            cur.execute("UPDATE people SET name = ?, password = ?, email = ?, number = ?, sessions = ?, weight = ?, admin = ?, color = ?, finish_date = ?, active = ?, activate_date = ? WHERE id = ?", (name, password, email, number, sessionsNumber, weight, admin, color, endDate, active, startDate, userId))

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