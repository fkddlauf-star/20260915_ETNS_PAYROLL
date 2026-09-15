from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .auth import admin_required
from .db import execute, query

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.route("/")
@admin_required
def index():
    users = query("SELECT * FROM pr_users ORDER BY created_at")
    return render_template("users.html", users=users)


@bp.route("/create", methods=["POST"])
@admin_required
def create():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "employee")
    employee_id = request.form.get("employee_id", "").strip() or None

    if not username or not password or not display_name:
        flash("아이디/비밀번호/이름을 모두 입력해주세요.")
        return redirect(url_for("users.index"))

    existing = query("SELECT id FROM pr_users WHERE username = %s", (username,), fetch="one")
    if existing:
        flash("이미 사용 중인 아이디입니다.")
        return redirect(url_for("users.index"))

    execute(
        """
        INSERT INTO pr_users (username, password_hash, display_name, role, employee_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (username, generate_password_hash(password), display_name, role, employee_id),
    )
    flash(f"계정 '{username}'이(가) 생성되었습니다.")
    return redirect(url_for("users.index"))


@bp.route("/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_active(user_id):
    execute(
        "UPDATE pr_users SET is_active = NOT is_active WHERE id = %s", (user_id,)
    )
    return redirect(url_for("users.index"))
