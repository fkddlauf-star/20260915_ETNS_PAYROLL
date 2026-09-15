from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .db import query

bp = Blueprint("auth", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            flash("관리자만 접근할 수 있는 화면입니다.")
            return redirect(url_for("dashboard.employee_home"))
        return view(*args, **kwargs)

    return wrapped


def current_user():
    if "user_id" not in session:
        return None
    return {
        "id": session["user_id"],
        "username": session["username"],
        "display_name": session["display_name"],
        "role": session["role"],
        "employee_id": session.get("employee_id"),
    }


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = query(
            "SELECT * FROM pr_users WHERE username = %s", (username,), fetch="one"
        )

        if not user or not check_password_hash(user["password_hash"], password):
            flash("아이디 또는 비밀번호가 올바르지 않습니다.")
            return redirect(url_for("auth.login"))

        if not user["is_active"]:
            flash("비활성화된 계정입니다. 관리자에게 문의하세요.")
            return redirect(url_for("auth.login"))

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"]
        session["role"] = user["role"]
        session["employee_id"] = user["employee_id"]

        if user["role"] == "admin":
            return redirect(url_for("dashboard.admin_home"))
        return redirect(url_for("dashboard.employee_home"))

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
