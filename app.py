from flask import Flask, render_template, url_for
# from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///main.db'
# db = SQLAlchemy(app)

# class People(db.Model):
#     id = db.Column(db.Ingeger, primary_key=True)
#     name = db.Column(db.String(255), nullable=False)
#     monday = db.Column(db.Bool)
#     tuesday = db.Column(db.Bool)

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/admin")
def admin():
    return render_template('admin.html')

if __name__ == "__main__":
    app.run(debug=True)