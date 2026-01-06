import streamlit as st
import tempfile
import os
from datetime import datetime

from pdf_processor import process_pdf, get_financial_context
from data_store import (
    save_extracted_data,
    load_extracted_data,
    list_saved_files,
    get_all_data_context,
    delete_extracted_data,
    save_chat_history,
    load_chat_history,
    list_chat_sessions,
    delete_chat_history
)
from claude_client import ClaudeClient


def init_session_state():
    """세션 상태 초기화"""
    if "current_session" not in st.session_state:
        st.session_state.current_session = datetime.now().strftime("%Y%m%d_%H%M%S")
    if "messages" not in st.session_state:
        # 이전 세션 히스토리 로드 시도
        st.session_state.messages = load_chat_history(st.session_state.current_session)
    if "financial_context" not in st.session_state:
        st.session_state.financial_context = ""
    if "client" not in st.session_state:
        try:
            st.session_state.client = ClaudeClient()
        except ValueError:
            st.session_state.client = None


def display_chat_history():
    """채팅 히스토리 표시"""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def process_uploaded_files(uploaded_files):
    """업로드된 여러 PDF 파일 처리"""
    total = len(uploaded_files)
    success_count = 0

    progress_bar = st.progress(0)
    status_text = st.empty()

    for idx, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"분석 중: {uploaded_file.name} ({idx + 1}/{total})")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        try:
            data = process_pdf(tmp_path)
            save_extracted_data(data, uploaded_file.name)
            success_count += 1
        except Exception as e:
            st.error(f"'{uploaded_file.name}' 처리 실패: {str(e)}")
        finally:
            os.unlink(tmp_path)

        progress_bar.progress((idx + 1) / total)

    progress_bar.empty()
    status_text.empty()

    st.success(f"✅ {success_count}/{total}개 파일 분석 완료!")

    # 컨텍스트 업데이트
    st.session_state.financial_context = get_all_data_context()


def load_session(session_id: str):
    """이전 세션 로드"""
    st.session_state.current_session = session_id
    st.session_state.messages = load_chat_history(session_id)


def main():
    st.set_page_config(
        page_title="재무제표 챗봇",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 재무제표 분석 챗봇")
    st.caption("PDF 재무제표를 업로드하고 질문하세요")

    init_session_state()

    # 사이드바: 파일 관리
    with st.sidebar:
        st.header("📁 파일 관리")

        # API 키 상태 확인
        if st.session_state.client is None:
            st.error("⚠️ API 키가 설정되지 않았습니다")
            st.info("`.env` 파일에 ANTHROPIC_API_KEY를 설정하세요")
        else:
            st.success("✅ API 연결됨")

        st.divider()

        # PDF 업로드 (다중 파일)
        st.subheader("PDF 업로드")
        uploaded_files = st.file_uploader(
            "재무제표 PDF 파일 선택",
            type=["pdf"],
            accept_multiple_files=True,
            help="연도별 재무제표 PDF를 여러 개 선택하세요 (5개 이상 가능)"
        )

        if uploaded_files:
            st.caption(f"📎 {len(uploaded_files)}개 파일 선택됨")
            if st.button("📤 전체 파일 분석", use_container_width=True):
                process_uploaded_files(uploaded_files)

        st.divider()

        # 저장된 파일 목록
        st.subheader("저장된 데이터")
        saved_files = list_saved_files()

        if saved_files:
            for filename in saved_files:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.text(filename[:20] + "..." if len(filename) > 20 else filename)
                with col2:
                    if st.button("🗑️", key=f"del_{filename}"):
                        delete_extracted_data(filename)
                        st.session_state.financial_context = get_all_data_context()
                        st.rerun()

            # 컨텍스트 로드 버튼
            if st.button("🔄 데이터 새로고침", use_container_width=True):
                st.session_state.financial_context = get_all_data_context()
                st.success("데이터 로드 완료!")
        else:
            st.info("업로드된 파일이 없습니다")

        st.divider()

        # 대화 히스토리 관리
        st.subheader("💬 대화 히스토리")

        # 현재 세션 표시
        st.caption(f"현재: {st.session_state.current_session}")

        # 새 대화 시작
        if st.button("➕ 새 대화 시작", use_container_width=True):
            # 현재 대화 저장
            if st.session_state.messages:
                save_chat_history(st.session_state.messages, st.session_state.current_session)
            # 새 세션 시작
            st.session_state.current_session = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.session_state.messages = []
            st.rerun()

        # 이전 대화 목록
        sessions = list_chat_sessions()
        if sessions:
            st.caption("이전 대화:")
            for session in sessions[:10]:  # 최근 10개만 표시
                session_id = session["session_id"]
                msg_count = session["message_count"]

                col1, col2 = st.columns([3, 1])
                with col1:
                    # 날짜 포맷 변환
                    try:
                        date_str = datetime.strptime(session_id, "%Y%m%d_%H%M%S").strftime("%m/%d %H:%M")
                    except:
                        date_str = session_id[:10]

                    if st.button(f"📝 {date_str} ({msg_count}건)", key=f"load_{session_id}", use_container_width=True):
                        # 현재 대화 저장 후 로드
                        if st.session_state.messages:
                            save_chat_history(st.session_state.messages, st.session_state.current_session)
                        load_session(session_id)
                        st.rerun()

                with col2:
                    if st.button("🗑️", key=f"del_session_{session_id}"):
                        delete_chat_history(session_id)
                        st.rerun()

    # 메인 영역: 채팅
    if not st.session_state.financial_context:
        st.session_state.financial_context = get_all_data_context()

    # 데이터 없음 경고
    if "저장된 재무 데이터가 없습니다" in st.session_state.financial_context:
        st.warning("📌 먼저 사이드바에서 재무제표 PDF를 업로드해주세요")

    # 채팅 히스토리 표시
    display_chat_history()

    # 채팅 입력
    if prompt := st.chat_input("재무제표에 대해 질문하세요..."):
        if st.session_state.client is None:
            st.error("API 키가 설정되지 않았습니다")
            return

        # 사용자 메시지 추가
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # AI 응답 생성
        with st.chat_message("assistant"):
            with st.spinner("답변 생성 중..."):
                # 대화 히스토리 (마지막 메시지 제외)
                history = st.session_state.messages[:-1]

                response = st.session_state.client.ask(
                    question=prompt,
                    financial_context=st.session_state.financial_context,
                    conversation_history=history
                )

                st.markdown(response)

        # 응답 저장
        st.session_state.messages.append({"role": "assistant", "content": response})

        # 대화 히스토리 파일로 저장
        save_chat_history(st.session_state.messages, st.session_state.current_session)


if __name__ == "__main__":
    main()
