import streamlit as st
import tempfile
import os
from datetime import datetime
from pathlib import Path

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
        st.session_state.messages = load_chat_history(st.session_state.current_session)
    if "financial_context" not in st.session_state:
        st.session_state.financial_context = ""
    if "client" not in st.session_state:
        try:
            st.session_state.client = ClaudeClient()
        except ValueError:
            st.session_state.client = None
    if "selected_companies" not in st.session_state:
        st.session_state.selected_companies = []
    if "company_data" not in st.session_state:
        st.session_state.company_data = {}


def get_company_folders():
    """data 폴더 내의 회사별 폴더 목록 반환"""
    data_dir = Path("data")
    if not data_dir.exists():
        data_dir.mkdir(parents=True)
        return []
    
    companies = [d.name for d in data_dir.iterdir() if d.is_dir()]
    return sorted(companies)


def save_company_file(uploaded_file, company_name):
    """회사별 폴더에 PDF 저장 및 분석"""
    company_dir = Path("data") / company_name
    company_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = company_dir / uploaded_file.name
    
    # 파일 저장
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    
    # PDF 분석
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        tmp_path = tmp_file.name
    
    try:
        data = process_pdf(tmp_path)
        # 회사명을 포함하여 저장
        data['company_name'] = company_name
        save_extracted_data(data, f"{company_name}_{uploaded_file.name}")
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        os.unlink(tmp_path)


def get_company_files(company_name):
    """특정 회사의 저장된 파일 목록 반환"""
    company_dir = Path("data") / company_name
    if not company_dir.exists():
        return []
    
    return sorted([f.name for f in company_dir.glob("*.pdf")])


def get_selected_companies_context():
    """선택된 회사들의 재무 데이터만 컨텍스트로 반환"""
    if not st.session_state.selected_companies:
        return get_all_data_context()
    
    saved_files = list_saved_files()
    selected_data = []
    
    for filename in saved_files:
        for company in st.session_state.selected_companies:
            if filename.startswith(f"{company}_"):
                data = load_extracted_data(filename)
                if data:
                    selected_data.append(data)
    
    if not selected_data:
        return "선택된 회사의 재무 데이터가 없습니다."
    
    context_parts = []
    for data in selected_data:
        company_name = data.get('company_name', '알 수 없음')
        context_parts.append(f"\n\n=== {company_name} 재무 데이터 ===\n")
        context_parts.append(data.get('text', ''))
    
    return "\n".join(context_parts)


def display_chat_history():
    """채팅 히스토리 표시"""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def load_session(session_id: str):
    """이전 세션 로드"""
    st.session_state.current_session = session_id
    st.session_state.messages = load_chat_history(session_id)


def main():
    st.set_page_config(
        page_title="무엇이든 물어보세요?",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 무엇이든 물어보세요?")
    st.caption("회사별 재무제표를 업로드하고 비교 분석하세요")

    init_session_state()

    # 사이드바: 회사 및 파일 관리
    with st.sidebar:
        st.header("🏢 회사별 데이터 관리")

        # API 키 상태 확인
        if st.session_state.client is None:
            st.error("⚠️ API 키가 설정되지 않았습니다")
            st.info("`.env` 파일에 ANTHROPIC_API_KEY를 설정하세요")
        else:
            st.success("✅ API 연결됨")

        st.divider()

        # 새 회사 추가
        st.subheader("➕ 새 회사 추가")
        new_company = st.text_input("회사명 입력", placeholder="예: 우리회사")
        
        if new_company and st.button("회사 추가", use_container_width=True):
            company_dir = Path("data") / new_company
            company_dir.mkdir(parents=True, exist_ok=True)
            st.success(f"✅ '{new_company}' 폴더 생성됨")
            st.rerun()

        st.divider()

        # 회사별 파일 업로드
        st.subheader("📤 파일 업로드")
        companies = get_company_folders()
        
        if companies:
            selected_company = st.selectbox("회사 선택", [""] + companies)
            
            if selected_company:
                uploaded_files = st.file_uploader(
                    f"{selected_company}의 재무제표",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key=f"upload_{selected_company}"
                )
                
                if uploaded_files and st.button("📥 업로드 및 분석", use_container_width=True):
                    progress_bar = st.progress(0)
                    success_count = 0
                    
                    for idx, file in enumerate(uploaded_files):
                        success, error = save_company_file(file, selected_company)
                        if success:
                            success_count += 1
                        else:
                            st.error(f"❌ {file.name}: {error}")
                        progress_bar.progress((idx + 1) / len(uploaded_files))
                    
                    st.success(f"✅ {success_count}/{len(uploaded_files)}개 파일 분석 완료!")
                    st.rerun()
        else:
            st.info("먼저 회사를 추가하세요")

        st.divider()

        # 비교 분석할 회사 선택
        st.subheader("🔍 비교 분석 대상")
        
        if companies:
            # 전체 선택/해제
            col1, col2 = st.columns(2)
            with col1:
                if st.button("전체 선택", use_container_width=True):
                    st.session_state.selected_companies = companies.copy()
                    st.rerun()
            with col2:
                if st.button("선택 해제", use_container_width=True):
                    st.session_state.selected_companies = []
                    st.rerun()
            
            # 회사별 체크박스
            for company in companies:
                files = get_company_files(company)
                file_count = len(files)
                
                is_selected = company in st.session_state.selected_companies
                
                if st.checkbox(
                    f"📁 {company} ({file_count}개 파일)",
                    value=is_selected,
                    key=f"check_{company}"
                ):
                    if company not in st.session_state.selected_companies:
                        st.session_state.selected_companies.append(company)
                else:
                    if company in st.session_state.selected_companies:
                        st.session_state.selected_companies.remove(company)
            
            # 컨텍스트 업데이트 버튼
            if st.button("🔄 분석 데이터 갱신", use_container_width=True):
                st.session_state.financial_context = get_selected_companies_context()
                st.success("✅ 데이터 갱신 완료!")
        
        st.divider()

        # 회사별 파일 관리
        st.subheader("📋 저장된 파일")
        
        if companies:
            for company in companies:
                with st.expander(f"📁 {company}"):
                    files = get_company_files(company)
                    
                    if files:
                        for file in files:
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.text(file)
                            with col2:
                                if st.button("🗑️", key=f"del_{company}_{file}"):
                                    file_path = Path("data") / company / file
                                    file_path.unlink()
                                    # 분석 데이터도 삭제
                                    delete_extracted_data(f"{company}_{file}")
                                    st.rerun()
                        
                        # 회사 폴더 전체 삭제
                        if st.button(f"🗑️ {company} 전체 삭제", key=f"del_company_{company}"):
                            import shutil
                            shutil.rmtree(Path("data") / company)
                            st.rerun()
                    else:
                        st.caption("파일 없음")

        st.divider()

        # 대화 히스토리 관리
        st.subheader("💬 대화 히스토리")
        st.caption(f"현재: {st.session_state.current_session}")

        if st.button("➕ 새 대화 시작", use_container_width=True):
            if st.session_state.messages:
                save_chat_history(st.session_state.messages, st.session_state.current_session)
            st.session_state.current_session = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.session_state.messages = []
            st.rerun()

        sessions = list_chat_sessions()
        if sessions:
            st.caption("이전 대화:")
            for session in sessions[:10]:
                session_id = session["session_id"]
                msg_count = session["message_count"]

                col1, col2 = st.columns([3, 1])
                with col1:
                    try:
                        date_str = datetime.strptime(session_id, "%Y%m%d_%H%M%S").strftime("%m/%d %H:%M")
                    except:
                        date_str = session_id[:10]

                    if st.button(f"📝 {date_str} ({msg_count}건)", key=f"load_{session_id}", use_container_width=True):
                        if st.session_state.messages:
                            save_chat_history(st.session_state.messages, st.session_state.current_session)
                        load_session(session_id)
                        st.rerun()

                with col2:
                    if st.button("🗑️", key=f"del_session_{session_id}"):
                        delete_chat_history(session_id)
                        st.rerun()

    # 메인 영역: 채팅
    # 선택된 회사 표시
    if st.session_state.selected_companies:
        st.info(f"🔍 분석 대상: {', '.join(st.session_state.selected_companies)}")
    
    # 컨텍스트 로드
    if not st.session_state.financial_context:
        st.session_state.financial_context = get_selected_companies_context()

    # 데이터 없음 경고
    if "재무 데이터가 없습니다" in st.session_state.financial_context:
        st.warning("📌 먼저 사이드바에서 회사를 추가하고 재무제표를 업로드하세요")
        
        # 예시 질문 표시
        with st.expander("💡 사용 예시"):
            st.markdown("""
            ### 단일 회사 분석
            - "우리회사의 2023년 매출액은?"
            - "최근 5년간 영업이익 추이를 보여줘"
            
            ### 다중 회사 비교
            - "우리회사와 경쟁사A의 매출액을 비교해줘"
            - "세 회사의 부채비율을 표로 정리해줘"
            - "영업이익률이 가장 높은 회사는?"
            - "ROE가 가장 좋은 회사 순위를 알려줘"
            """)

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
                history = st.session_state.messages[:-1]

                # 비교 분석 힌트 추가
                enhanced_context = st.session_state.financial_context
                if len(st.session_state.selected_companies) > 1:
                    enhanced_context = f"""
다음은 {len(st.session_state.selected_companies)}개 회사의 재무 데이터입니다.
회사별 비교 분석 시 명확하게 구분하여 답변해주세요.

{st.session_state.financial_context}
"""

                response = st.session_state.client.ask(
                    question=prompt,
                    financial_context=enhanced_context,
                    conversation_history=history
                )

                st.markdown(response)

        # 응답 저장
        st.session_state.messages.append({"role": "assistant", "content": response})
        save_chat_history(st.session_state.messages, st.session_state.current_session)


if __name__ == "__main__":
    main()
