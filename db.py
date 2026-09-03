import io
from datetime import datetime

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

STATUSES = ["미확인", "확인필요", "확정", "보류"]
TYPES = ["text", "image", "link"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PROJECTS_HEADERS = ["id", "name", "created_at"]
MEMOS_HEADERS = [
    "id",
    "project_id",
    "type",
    "title",
    "content",
    "image_path",
    "link_url",
    "status",
    "order_index",
    "created_at",
    "updated_at",
]


def _check_secrets():
    required = ["gcp_service_account", "sheet_id", "drive_folder_id"]
    try:
        missing = [k for k in required if k not in st.secrets]
    except Exception:
        missing = required
    if missing:
        st.error(
            "구글 연동 설정이 없습니다. `설정방법.md`를 참고해 Streamlit secrets를 설정해주세요. "
            f"(누락된 설정: {', '.join(missing)})"
        )
        st.stop()


@st.cache_resource
def _get_credentials():
    _check_secrets()
    return Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=SCOPES)


@st.cache_resource
def _get_gspread_client():
    return gspread.authorize(_get_credentials())


@st.cache_resource
def _get_drive_service():
    return build("drive", "v3", credentials=_get_credentials())


def _open_spreadsheet():
    try:
        return _get_gspread_client().open_by_key(st.secrets["sheet_id"])
    except PermissionError:
        client_email = dict(st.secrets["gcp_service_account"]).get("client_email", "(확인 불가)")
        st.error(
            "구글시트에 접근 권한이 없습니다. 시트를 열고 오른쪽 위 '공유' 버튼으로 "
            f"서비스계정 이메일({client_email})을 편집자로 추가해주세요."
        )
        st.stop()
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(
            "sheet_id로 지정한 구글시트를 찾을 수 없습니다. `설정방법.md`를 참고해 "
            "secrets.toml의 sheet_id 값이 시트 URL의 /d/와 /edit 사이 문자열과 정확히 일치하는지 확인해주세요."
        )
        st.stop()
    except gspread.exceptions.APIError as e:
        st.error(
            "구글시트 API 호출이 일시적으로 실패했습니다 (사용량 제한일 수 있어요). "
            f"잠시 후 새로고침해주세요. ({e})"
        )
        st.stop()


def _get_or_create_worksheet(name, headers):
    sh = _open_spreadsheet()
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=len(headers))
        ws.append_row(headers)
        return ws


@st.cache_resource
def _projects_ws():
    return _get_or_create_worksheet("projects", PROJECTS_HEADERS)


@st.cache_resource
def _memos_ws():
    return _get_or_create_worksheet("memos", MEMOS_HEADERS)


def _find_row(records, memo_id):
    for i, r in enumerate(records):
        if r["id"] == memo_id:
            return i + 2  # header row + 1-indexing
    return None


def init_db():
    _check_secrets()
    _projects_ws()
    _memos_ws()


def add_project(name):
    ws = _projects_ws()
    records = ws.get_all_records()
    new_id = max((r["id"] for r in records), default=0) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([new_id, name, now])
    return new_id


def fetch_projects():
    records = _projects_ws().get_all_records()
    records.sort(key=lambda r: r["created_at"], reverse=True)
    return records


def delete_project(project_id):
    memos_ws = _memos_ws()
    memo_records = memos_ws.get_all_records()
    rows = [i + 2 for i, r in enumerate(memo_records) if r["project_id"] == project_id]
    for row in sorted(rows, reverse=True):
        memos_ws.delete_rows(row)

    projects_ws = _projects_ws()
    project_records = projects_ws.get_all_records()
    row = _find_row(project_records, project_id)
    if row:
        projects_ws.delete_rows(row)


def add_memo(project_id, type_, title, content, image_path, link_url, status):
    ws = _memos_ws()
    records = ws.get_all_records()
    new_id = max((r["id"] for r in records), default=0) + 1
    max_order = max(
        (r["order_index"] for r in records if r["project_id"] == project_id), default=0
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row(
        [
            new_id,
            project_id,
            type_,
            title or "",
            content or "",
            image_path or "",
            link_url or "",
            status,
            max_order + 1,
            now,
            now,
        ]
    )
    return new_id


def fetch_memos(project_id, statuses=None):
    records = [r for r in _memos_ws().get_all_records() if r["project_id"] == project_id]
    if statuses:
        records = [r for r in records if r["status"] in statuses]
    records.sort(key=lambda r: r["order_index"])
    return records


def get_memo(memo_id):
    for r in _memos_ws().get_all_records():
        if r["id"] == memo_id:
            return r
    return None


def update_memo(memo_id, title, content, image_path, link_url, status):
    ws = _memos_ws()
    records = ws.get_all_records()
    row = _find_row(records, memo_id)
    if row is None:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.batch_update(
        [
            {
                "range": f"D{row}:H{row}",
                "values": [[title or "", content or "", image_path or "", link_url or "", status]],
            },
            {"range": f"K{row}", "values": [[now]]},
        ]
    )


def delete_memo(memo_id):
    ws = _memos_ws()
    row = _find_row(ws.get_all_records(), memo_id)
    if row:
        ws.delete_rows(row)


def move_memo(memo_id, direction):
    ws = _memos_ws()
    records = ws.get_all_records()
    memo = next((r for r in records if r["id"] == memo_id), None)
    if memo is None:
        return

    siblings = sorted(
        (r for r in records if r["project_id"] == memo["project_id"]),
        key=lambda r: r["order_index"],
    )
    pos = siblings.index(memo)
    if direction == "up" and pos > 0:
        neighbor = siblings[pos - 1]
    elif direction == "down" and pos < len(siblings) - 1:
        neighbor = siblings[pos + 1]
    else:
        return

    memo_row = _find_row(records, memo["id"])
    neighbor_row = _find_row(records, neighbor["id"])
    ws.batch_update(
        [
            {"range": f"I{memo_row}", "values": [[neighbor["order_index"]]]},
            {"range": f"I{neighbor_row}", "values": [[memo["order_index"]]]},
        ]
    )


def upload_image(project_id, uploaded_file):
    service = _get_drive_service()
    metadata = {
        "name": f"project{project_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{uploaded_file.name}",
        "parents": [st.secrets["drive_folder_id"]],
    }
    media = MediaIoBaseUpload(
        io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type or "application/octet-stream"
    )
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return file["id"]


@st.cache_data(show_spinner=False)
def get_image_bytes(file_id):
    service = _get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()
