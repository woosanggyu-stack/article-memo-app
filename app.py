import streamlit as st

from db import (
    STATUSES,
    init_db,
    add_project,
    fetch_projects,
    delete_project,
    add_memo,
    fetch_memos,
    get_memo,
    update_memo,
    delete_memo,
    move_memo,
    upload_image,
    get_image_bytes,
)
from scraper import fetch_link_meta

st.set_page_config(page_title="기사 메모", page_icon="🗂️", layout="wide")
init_db()

TYPE_LABELS = {"text": "텍스트", "image": "이미지", "link": "링크"}


# ---------- 사이드바: 프로젝트 관리 ----------
st.sidebar.title("🗂️ 기사 프로젝트")

projects = fetch_projects()
project_names = {p["id"]: p["name"] for p in projects}

if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = projects[0]["id"] if projects else None

if projects:
    options = list(project_names.keys())
    current_index = options.index(st.session_state.current_project_id) if st.session_state.current_project_id in options else 0
    selected_id = st.sidebar.selectbox(
        "프로젝트 선택",
        options,
        index=current_index,
        format_func=lambda pid: project_names[pid],
    )
    st.session_state.current_project_id = selected_id
else:
    st.sidebar.info("아직 프로젝트가 없습니다. 아래에서 새로 만들어주세요.")

st.sidebar.divider()
with st.sidebar.form("new_project_form", clear_on_submit=True):
    new_project_name = st.text_input("새 프로젝트 이름")
    if st.form_submit_button("만들기") and new_project_name.strip():
        new_id = add_project(new_project_name.strip())
        st.session_state.current_project_id = new_id
        st.rerun()

if projects:
    st.sidebar.divider()
    with st.sidebar.expander("현재 프로젝트 삭제"):
        st.write(f"'{project_names[st.session_state.current_project_id]}' 프로젝트와 모든 메모가 삭제됩니다.")
        if st.button("삭제 확인", type="primary"):
            delete_project(st.session_state.current_project_id)
            st.session_state.current_project_id = None
            st.rerun()

if not st.session_state.current_project_id:
    st.info("왼쪽 사이드바에서 프로젝트를 먼저 만들어주세요.")
    st.stop()

project_id = st.session_state.current_project_id
st.title(f"🗂️ {project_names[project_id]}")

tab_write, tab_cards, tab_draft = st.tabs(["메모 작성", "카드보기", "초안 엮기"])

# ---------- 탭 1: 메모 작성 ----------
with tab_write:
    memo_type_label = st.radio("메모 유형", list(TYPE_LABELS.values()), horizontal=True)
    memo_type = {v: k for k, v in TYPE_LABELS.items()}[memo_type_label]

    default_title = st.session_state.get("scraped_title", "") if memo_type == "link" else ""
    title = st.text_input("제목 (선택)", value=default_title, key="write_title")
    status = st.selectbox("상태", STATUSES, key="write_status")

    content = ""
    image_path = None
    link_url = None
    uploaded_file = None

    if memo_type == "text":
        content = st.text_area("내용", height=200, key="write_content_text")
    elif memo_type == "image":
        uploaded_file = st.file_uploader(
            "이미지 업로드", type=["png", "jpg", "jpeg", "gif", "webp"], key="write_image_file"
        )
        content = st.text_area("설명/메모 (선택)", height=100, key="write_content_image")
        if uploaded_file:
            st.image(uploaded_file, width=300)
    elif memo_type == "link":
        link_url = st.text_input("URL", key="write_link_url")
        if st.button("스크랩") and link_url.strip():
            meta = fetch_link_meta(link_url.strip())
            st.session_state["scraped_title"] = meta["title"]
            st.session_state["scraped_desc"] = meta["description"]
            if not meta["title"] and not meta["description"]:
                st.warning("자동으로 정보를 가져오지 못했습니다. 직접 입력해주세요.")
            st.rerun()
        content = st.text_area(
            "내용 (스크랩된 요약 + 직접 메모)",
            value=st.session_state.get("scraped_desc", ""),
            height=150,
            key="write_content_link",
        )

    if st.button("저장", type="primary"):
        errors = []
        if memo_type == "text" and not content.strip():
            errors.append("내용을 입력해주세요.")
        if memo_type == "image" and not uploaded_file:
            errors.append("이미지를 업로드해주세요.")
        if memo_type == "link" and not (link_url and link_url.strip()):
            errors.append("URL을 입력해주세요.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            if memo_type == "image":
                image_path = upload_image(project_id, uploaded_file)
            add_memo(
                project_id,
                memo_type,
                title.strip() if title else None,
                content.strip() if content else None,
                image_path,
                link_url.strip() if link_url else None,
                status,
            )
            for k in (
                "write_title",
                "write_content_text",
                "write_content_image",
                "write_image_file",
                "write_link_url",
                "write_content_link",
                "scraped_title",
                "scraped_desc",
            ):
                st.session_state.pop(k, None)
            st.success("메모가 저장되었습니다.")
            st.rerun()

# ---------- 탭 2: 카드보기 ----------
with tab_cards:
    filter_statuses = st.multiselect("상태 필터", STATUSES, default=STATUSES)
    memos = fetch_memos(project_id, statuses=filter_statuses if filter_statuses else None)

    if not memos:
        st.info("표시할 메모가 없습니다.")

    for memo in memos:
        edit_key = f"editing_{memo['id']}"
        with st.container(border=True):
            header_cols = st.columns([6, 1, 1, 1, 1])
            header_cols[0].markdown(
                f"**[{TYPE_LABELS[memo['type']]}] {memo['title'] or '(제목 없음)'}**  ·  상태: {memo['status']}"
            )
            if header_cols[1].button("▲", key=f"up_{memo['id']}"):
                move_memo(memo["id"], "up")
                st.rerun()
            if header_cols[2].button("▼", key=f"down_{memo['id']}"):
                move_memo(memo["id"], "down")
                st.rerun()
            if header_cols[3].button("수정", key=f"edit_{memo['id']}"):
                st.session_state[edit_key] = not st.session_state.get(edit_key, False)
            if header_cols[4].button("삭제", key=f"del_{memo['id']}"):
                delete_memo(memo["id"])
                st.rerun()

            if st.session_state.get(edit_key):
                new_title = st.text_input("제목", value=memo["title"] or "", key=f"title_{memo['id']}")
                new_status = st.selectbox(
                    "상태", STATUSES, index=STATUSES.index(memo["status"]), key=f"status_{memo['id']}"
                )
                new_content = st.text_area("내용", value=memo["content"] or "", key=f"content_{memo['id']}")
                new_link_url = memo["link_url"]
                if memo["type"] == "link":
                    new_link_url = st.text_input("URL", value=memo["link_url"] or "", key=f"link_{memo['id']}")
                new_image_path = memo["image_path"]
                if memo["type"] == "image":
                    if memo["image_path"]:
                        st.image(get_image_bytes(memo["image_path"]), width=200)
                    replacement = st.file_uploader(
                        "이미지 교체 (선택)", type=["png", "jpg", "jpeg", "gif", "webp"], key=f"img_{memo['id']}"
                    )
                    if replacement:
                        new_image_path = upload_image(project_id, replacement)

                if st.button("저장", key=f"save_{memo['id']}"):
                    update_memo(
                        memo["id"],
                        new_title.strip() if new_title else None,
                        new_content.strip() if new_content else None,
                        new_image_path,
                        new_link_url.strip() if new_link_url else None,
                        new_status,
                    )
                    st.session_state[edit_key] = False
                    st.rerun()
            else:
                if memo["type"] == "image" and memo["image_path"]:
                    st.image(get_image_bytes(memo["image_path"]), width=300)
                if memo["type"] == "link" and memo["link_url"]:
                    st.markdown(f"🔗 [{memo['link_url']}]({memo['link_url']})")
                if memo["content"]:
                    st.write(memo["content"])

# ---------- 탭 3: 초안 엮기 ----------
with tab_draft:
    draft_statuses = st.multiselect("엮을 상태 선택", STATUSES, default=["확정"], key="draft_statuses")
    memos = fetch_memos(project_id, statuses=draft_statuses if draft_statuses else None)

    parts = []
    for memo in memos:
        if memo["type"] == "image":
            label = memo["title"] or "[이미지 첨부]"
            parts.append(label)
        else:
            piece = ""
            if memo["title"]:
                piece += f"[{memo['title']}]\n"
            if memo["type"] == "link" and memo["link_url"]:
                piece += f"(출처: {memo['link_url']})\n"
            if memo["content"]:
                piece += memo["content"]
            parts.append(piece.strip())

    draft_text = "\n\n".join(p for p in parts if p)

    st.text_area("엮은 초안", value=draft_text, height=400)
    st.download_button(
        "텍스트 파일로 다운로드",
        data=draft_text,
        file_name=f"{project_names[project_id]}_초안.txt",
        mime="text/plain",
    )
