"""Personal Expense Tracker & Analysis System - Flask backend."""
import os, io, base64, math, random, sqlite3
from datetime import datetime, timedelta
from functools import wraps

import matplotlib
matplotlib.use("Agg")              # non-GUI backend: draws charts to memory
import matplotlib.pyplot as plt
import pandas as pd
from flask import Flask, request, jsonify, session, render_template, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "expenses.db")
CATEGORIES = ["Food", "Travel", "Education", "Shopping", "Entertainment"]
COLORS = ["#E4572E", "#0B7A75", "#2E6FDB", "#F2A900", "#7B2CBF"]

app = Flask(__name__)
app.secret_key = "change-this-secret-key"   # needed for sessions


# ---------- Database helpers ----------
def get_db():
    """One SQLite connection per request."""
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """Create tables if they do not exist."""
    with sqlite3.connect(DB) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            is_sample INTEGER DEFAULT 0);
        """)


def login_required(f):
    """Block API access unless the user is logged in."""
    @wraps(f)
    def wrapper(*a, **kw):
        if "user_id" not in session:
            return jsonify(error="Please sign in first."), 401
        return f(*a, **kw)
    return wrapper


# ---------- Validation ----------
def validate_expense(data):
    """Return (clean_dict, error_message)."""
    try:
        date = str(data.get("date", "")).strip()
        category = str(data.get("category", "")).strip()
        desc = str(data.get("description", "")).strip()
        if not date or not category or not desc or str(data.get("amount", "")).strip() == "":
            return None, "All fields are required."
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return None, "Invalid date."
        if category not in CATEGORIES:
            return None, "Invalid category."
        try:
            amount = float(data.get("amount"))
        except (TypeError, ValueError):
            return None, "Amount must be a number."
        if math.isnan(amount) or math.isinf(amount) or amount <= 0:
            return None, "Amount must be greater than zero."
        if amount > 10_000_000:
            return None, "Amount is too large."
        return {"date": date, "category": category, "amount": round(amount, 2),
                "description": desc[:200]}, None
    except Exception:
        return None, "Invalid input."


# ---------- Pandas calculations ----------
def load_df(month=None):
    """Load the logged-in user's expenses into a DataFrame (optionally one month)."""
    sql = "SELECT date, category, amount, description FROM expenses WHERE user_id=?"
    params = [session["user_id"]]
    if month:
        sql += " AND date LIKE ?"
        params.append(month + "%")
    df = pd.read_sql_query(sql, get_db(), params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def calculate_summary(df, total_all):
    """Totals, average, highest/lowest and category-wise spending."""
    if df.empty:
        return {"total": 0, "total_all": total_all, "average": 0, "highest": None,
                "lowest": None, "count": 0, "by_category": {}}
    hi, lo = df.loc[df["amount"].idxmax()], df.loc[df["amount"].idxmin()]
    cat = df.groupby("category")["amount"].sum().round(2).to_dict()
    return {"total": round(float(df["amount"].sum()), 2), "total_all": total_all,
            "average": round(float(df["amount"].mean()), 2),
            "highest": {"amount": float(hi["amount"]), "category": hi["category"]},
            "lowest": {"amount": float(lo["amount"]), "category": lo["category"]},
            "count": int(len(df)), "by_category": cat}


# ---------- Matplotlib charts ----------
def make_chart(kind, df):
    """Draw one chart and return it as a base64 PNG string."""
    plt.rcParams.update({"font.size": 14})
    fig, ax = plt.subplots(figsize=(8, 5))
    try:
        if kind == "bar":
            s = df.groupby("category")["amount"].sum().reindex(CATEGORIES).fillna(0)
            ax.bar(s.index, s.values, color=COLORS, edgecolor="black", linewidth=1.5, label="Amount spent")
            ax.set(title="Category-wise Spending", xlabel="Category", ylabel="Amount (Rs.)")
            ax.legend()
        elif kind == "pie":
            s = df.groupby("category")["amount"].sum()
            cols = [COLORS[CATEGORIES.index(c)] for c in s.index]
            ax.pie(s.values, labels=None, colors=cols, autopct="%1.1f%%",
                   textprops={"fontsize": 14, "color": "white", "weight": "bold"},
                   wedgeprops={"edgecolor": "white", "linewidth": 2})
            ax.legend(s.index, loc="center left", bbox_to_anchor=(1, 0.5))
            ax.set_title("Category Share")
        elif kind == "line":
            s = df.groupby("date")["amount"].sum().sort_index()
            ax.plot(s.index, s.values, color="#0B7A75", marker="o", linewidth=3, label="Daily spending")
            ax.set(title="Spending Over Time", xlabel="Date", ylabel="Amount (Rs.)")
            ax.grid(alpha=0.4); ax.legend()
            fig.autofmt_xdate()
        elif kind == "hist":
            ax.hist(df["amount"], bins=min(10, max(3, len(df))), color="#2E6FDB",
                    edgecolor="black", linewidth=1.5, label="Expenses")
            ax.set(title="Distribution of Expense Amounts", xlabel="Amount (Rs.)", ylabel="Number of expenses")
            ax.legend()
        else:
            return None
        ax.title.set_fontsize(18); ax.title.set_fontweight("bold")
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
        return base64.b64encode(buf.getvalue()).decode()
    finally:
        plt.close(fig)               # always free memory


# ---------- Pages & auth ----------
@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES)


@app.route("/api/me")
def me():
    return jsonify(username=session.get("username"))


@app.route("/api/signup", methods=["POST"])
def signup():
    try:
        d = request.get_json(silent=True) or {}
        u, p = str(d.get("username", "")).strip(), str(d.get("password", ""))
        if len(u) < 3 or len(p) < 4:
            return jsonify(error="Username needs 3+ characters and password 4+."), 400
        db = get_db()
        try:
            cur = db.execute("INSERT INTO users(username,password_hash) VALUES(?,?)",
                             (u, generate_password_hash(p)))
            db.commit()
        except sqlite3.IntegrityError:
            return jsonify(error="Username already taken."), 400
        session.update(user_id=cur.lastrowid, username=u)
        return jsonify(username=u)
    except Exception:
        return jsonify(error="Sign-up failed."), 500


@app.route("/api/login", methods=["POST"])
def login():
    try:
        d = request.get_json(silent=True) or {}
        row = get_db().execute("SELECT * FROM users WHERE username=?",
                               (str(d.get("username", "")).strip(),)).fetchone()
        if not row or not check_password_hash(row["password_hash"], str(d.get("password", ""))):
            return jsonify(error="Wrong username or password."), 401
        session.update(user_id=row["id"], username=row["username"])
        return jsonify(username=row["username"])
    except Exception:
        return jsonify(error="Login failed."), 500


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify(ok=True)


# ---------- Expenses ----------
@app.route("/api/expenses", methods=["GET"])
@login_required
def list_expenses():
    try:
        field = request.args.get("sort", "date")
        order = request.args.get("order", "desc")
        field = field if field in ("date", "amount", "category") else "date"   # whitelist
        order = "ASC" if order == "asc" else "DESC"
        rows = get_db().execute(
            f"SELECT id,date,category,amount,description FROM expenses "
            f"WHERE user_id=? ORDER BY {field} {order}, id DESC", (session["user_id"],)).fetchall()
        return jsonify(expenses=[dict(r) for r in rows])
    except Exception:
        return jsonify(error="Could not load expenses."), 500


@app.route("/api/expenses", methods=["POST"])
@login_required
def add_expense():
    try:
        clean, err = validate_expense(request.get_json(silent=True) or {})
        if err:
            return jsonify(error=err), 400
        db = get_db()
        db.execute("INSERT INTO expenses(user_id,date,category,amount,description) VALUES(?,?,?,?,?)",
                   (session["user_id"], clean["date"], clean["category"], clean["amount"], clean["description"]))
        db.commit()
        return jsonify(ok=True)
    except Exception:
        return jsonify(error="Could not save expense."), 500


@app.route("/api/expenses/<int:eid>", methods=["DELETE"])
@login_required
def delete_expense(eid):
    try:
        db = get_db()
        db.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (eid, session["user_id"]))
        db.commit()
        return jsonify(ok=True)
    except Exception:
        return jsonify(error="Could not delete."), 500


@app.route("/api/sample", methods=["POST"])
@login_required
def sample():
    """Add or remove demo data (marked is_sample=1)."""
    try:
        db, uid = get_db(), session["user_id"]
        if (request.get_json(silent=True) or {}).get("action") == "remove":
            db.execute("DELETE FROM expenses WHERE user_id=? AND is_sample=1", (uid,))
        else:
            rnd = random.Random(42)
            for i in range(30):
                day = (datetime.now() - timedelta(days=rnd.randint(0, 60))).strftime("%Y-%m-%d")
                cat = rnd.choice(CATEGORIES)
                db.execute("INSERT INTO expenses(user_id,date,category,amount,description,is_sample) "
                           "VALUES(?,?,?,?,?,1)", (uid, day, cat, rnd.randint(50, 3000), f"Sample {cat} #{i+1}"))
        db.commit()
        return jsonify(ok=True)
    except Exception:
        return jsonify(error="Sample data failed."), 500


# ---------- Analysis & charts ----------
@app.route("/api/summary")
@login_required
def summary():
    try:
        month = request.args.get("month") or None
        total_all = float(load_df()["amount"].sum()) if not load_df().empty else 0
        return jsonify(calculate_summary(load_df(month), round(total_all, 2)))
    except Exception:
        return jsonify(error="Could not calculate summary."), 500


@app.route("/api/chart/<kind>")
@login_required
def chart(kind):
    try:
        df = load_df(request.args.get("month") or None)
        if df.empty:
            return jsonify(empty=True)
        img = make_chart(kind, df)
        return jsonify(image=img) if img else (jsonify(error="Unknown chart."), 404)
    except Exception:
        return jsonify(error="Chart failed."), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True)