"""Supabase Storage 연동 (원본 파일 저장/다운로드).

Vercel 같은 서버리스 환경은 로컬 디스크가 재배포/재시작마다 초기화되므로
업로드된 원본 파일은 로컬 디스크가 아닌 Supabase Storage에 저장한다.
"""

import os

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "payroll-uploads")

_HEADERS = {"Authorization": f"Bearer {SERVICE_KEY}", "apikey": SERVICE_KEY}


def upload_file(path, data, content_type="application/octet-stream"):
    """path 위치에 바이트(data)를 업로드한다. 이미 있으면 덮어쓴다."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    headers = {**_HEADERS, "Content-Type": content_type, "x-upsert": "true"}
    resp = requests.post(url, headers=headers, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def download_file(path):
    """path 위치의 바이트를 반환한다."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def delete_file(path):
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    requests.delete(url, headers=_HEADERS, timeout=30)
