import streamlit as st
import tempfile
import os
from datetime import datetime
from pathlib import Path
import json

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


# 영구 저장소 설정
PERSISTENT_DATA_DIR = Path("persistent_data")
PERSISTENT_DATA_DIR.mkdir(exist_ok=True)

COMPANIES_FILE = PERSISTENT_DATA_DIR / "companies.json"
PDF_STORAGE_DIR = PERSISTENT_DATA_DIR / "pdf_files"
PDF_STORAGE_DIR.mkdir(exist_ok=True)

# 토큰 제한 설정
MAX_CONTEXT_TOKENS = 150000
CHARS_PER_TOKEN = 4


def estimate_tokens(text):
    """텍스트의 대략적인 토큰 수 추정"""
    return len(text) // CHARS_PER_TOKEN


def truncate_context(context, max_tokens=MAX_CONTEXT_TOKENS):
    """컨텍스트를 토큰 제한 내로 축약"""
    estimated_tokens = estimate_tokens(context)
    
    if estimated_tokens <= max_tokens:
        return context, False
    
    ratio = max_tokens / estimated_tokens
    max_chars = int(len(context) * ratio * 0.95)
    
    truncated = context[:max_chars]
    truncated += "\n\n... [내용이 너무 길어 일부만 표시됩니다. 특정 회사나 연도를 지정하면 더 정확한 답변을 받을 수 있습니다.]"
    
    return truncated, True


def smart_context_selection(selected_companies, question):
    """질문에 가장 관련있는 데이터만 선택"""
    if not selected_companies:
        return get_all_data_context()
    
    saved_files = list_saved_files()
    selected_data = []
    
    import re
    years = re.findall(r'20\d{2}', question)
    
    for filename in saved_files:
        for company in selected_companies:
            if filename.startswith(f"{company}_"):
                if years:
                    if any(year in filename for year in years):
                        data = load_extracted_data(filename)
                        if data:
                            selected_data.append(data)
                else:
                    data = load_extracted_data(filename)
                    if data:
                        selected_data.append(data)
    
    if not selected_data:
        return "선택된 회사의 재무 데이터가 없습니다."
    
    context_parts = []
    for data in selected_data:
        company_name = data.get('company_name', '알 수 없음')
        filename = data.get('original_filename', '')
        
        context_parts.append(f"\n\n=== {company_name} - {filename} ===\n")
        context_parts.append(data.get('text', ''))
    
    full_context = "\n".join(context_parts)
    truncated_context, was_truncated = truncate_context(full_context)
    
    if was_truncated:
        warning = f"\n\n⚠️ 참고: 데이터가 많아 일부만 분석에 사용되었습니다. ({len(selected_data)}개 파일)"
        truncated_context = warning + truncated_context
    
    return truncated_context


def auto_migrate_legacy_data():
    """기존 데이터 자동 감지 및 마이그레이션"""
    extracted_dir = Path("extracted_data")
    if not extracted_dir.exists():
        return 0
    
    all_files = list(extracted_dir.glob("*.json"))
    legacy_files = []
    
    for file in all_files:
        filename = file.stem
        if '_' not in filename or not filename.split('_')[0] in get_all_company_names():
            legacy_files.append(file)
    
    if not legacy_files:
        return 0
    
    legacy_company = "기존데이터"
    companies = load_companies()
    
    if legacy_company not in companies:
        companies[legacy_company] = {
            "created_at": datetime.now().isoformat(),
            "file_count": 0,
            "auto_migrated": True
        }
        save_companies(companies)
    
    migrated = 0
    for old_file in legacy_files:
        try:
            with open(old_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'company_name' in data:
                continue
            
            original_name = old_file.name
            data['company_name'] = legacy_company
            data['original_filename'] = original_name.replace('.json', '')
            data['migrated_from_legacy'] = True
            
            new_filename = f"{legacy_company}_{original_name}"
            new_path = extracted_dir / new_filename
            
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            migrated += 1
            
            backup_dir = Path("backup_legacy_data")
            backup_dir.mkdir(exist_ok=True)
            old_file.rename(backup_dir / old_file.name)
            
        except Exception as e:
            pass
    
    if migrated > 0:
        update_company_file_count(legacy_company)
    
    return migrated


def get_all_company_names():
    """모든 회사명 반환"""
    companies = load_companies()
    return list(companies.keys())


def load_companies():
    """저장된 회사 목록 로드"""
    if COMPANIES_FILE.exists():
        try:
            with open(COMPANIES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_companies(companies):
    """회사 목록 저장"""
    with open(COMPANIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)


def save_pdf_permanently(uploaded_file, company_name):
    """PDF를 영구 저장소에 저장"""
    company_dir = PDF_STORAGE_DIR / company_name
    company_dir.mkdir(exist_ok=True)
    
    file_path = company_dir / uploaded_file.name
    with open(file_path, 'wb') as f:
        f.write(uploaded_file.getvalue())
    
    return file_path


def get_stored_pdfs(company_name):
    """저장된 PDF 파일 목록"""
    company_dir = PDF_STORAGE_DIR / company_name
    if not company_dir.exists():
        return []
    
    return sorted([f.name for f in company_dir.glob("*.pdf")])


def delete_pdf_file(company_name, filename):
    """PDF 파일 삭제"""
    file_path = PDF_STORAGE_DIR / company_name / filename
    if file_path.exists():
        file_path.unlink()


def delete_company_folder(company_name):
    """회사 폴더 전체 삭제"""
    company_dir = PDF_STORAGE_DIR / company_name
    if company_dir.exists():
        import shutil
        shutil.rmtree(company_dir)


def init_session_state():
    """세션 상태 초기화 - 대화 기록 보존 강화"""
    # 현재 세션 ID 유지 또는 생성
    if "current_session" not in st.session_state:
        # 가장 최근 세션 찾기
        sessions = list_chat_sessions()
        if sessions and len(sessions) > 0:
            # 최근 세션 자동 복구
            latest_session = sessions[0]["session_id"]
            st.session_state.current_session = latest_session
            st.session_state.session_restored = True
        else:
            st.session_state.current_session = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 메시지 로드
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
    
    if "companies" not in st.session_state:
        migrated_count = auto_migrate_legacy_data()
        if migrated_count > 0:
            st.session_state.migration_message = f"✅ 기존 데이터 {migrated_count}개를 '기존데이터' 회사로 자동 이동했습니다."
        st.session_state.companies = load_companies()


def get_company_folders():
    """저장된 회사 목록 반환"""
    companies = load_companies()
    return sorted(companies.keys())


def add_company(company_name):
    """새 회사 추가"""
    companies = load_companies()
    if company_name not in companies:
        companies[company_name] = {
            "created_at": datetime.now().isoformat(),
            "file_count": 0
        }
        save_companies(companies)
        st.session_state.companies = companies
        return True
    return False


def update_company_file_count(company_name):
    """회사의 파일 개수 업데이트"""
    companies = load_companies()
    if company_name in companies:
        files = get_company_files(company_name)
        companies[company_name]["file_count"] = len(files)
        save_companies(companies)


def save_company_file(uploaded_file, company_name):
    """PDF 저장 및 분석"""
    try:
        pdf_path = save_pdf_permanently(uploaded_file, company_name)
        data = process_pdf(str(pdf_path))
        
        data['company_name'] = company_name
        data['original_filename'] = uploaded_file.name
        data['stored_path'] = str(pdf_path)
        
        estimated_tokens = estimate_tokens(data.get('text', ''))
        
        if estimated_tokens > 50000:
            st.warning(f"⚠️ 큰 파일: 약 {estimated_tokens:,} 토큰. 특정 연도나 항목을 지정해서 질문하면 더 정확합니다.")
        
        save_extracted_data(data, f"{company_name}_{uploaded_file.name}")
        update_company_file_count(company_name)
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def get_company_files(company_name):
    """회사의 파일 목록 반환"""
    saved_files = list_saved_files()
    company_files = []
    
    for filename in saved_files:
        if filename.startswith(f"{company_name}_"):
            original_name = filename[len(company_name)+1:]
            if original_name.endswith('.json'):
                original_name = original_name[:-5]
            company_files.append(original_name)
    
    return sorted(set(company_files))


def get_selected_companies_context():
    """선택된 회사들의 재무 데이터"""
    if not st.session_state.selected_companies:
        context = get_all_data_context()
        truncated, was_truncated = truncate_context(context)
        if was_truncated:
            st.warning("⚠️ 데이터가 많아 일부만 표시됩니다. 특정 회사나 연도를 선택하면 더 정확합니다.")
        return truncated
    
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
    total_tokens = 0
    
    for data in selected_data:
        company_name = data.get('company_name', '알 수 없음')
        filename = data.get('original_filename', '')
        text = data.get('text', '')
        
        tokens = estimate_tokens(text)
        total_tokens += tokens
        
        context_parts.append(f"\n\n=== {company_name} - {filename} ===\n")
        context_parts.append(text)
    
    full_context = "\n".join(context_parts)
    truncated, was_truncated = truncate_context(full_context)
    
    if was_truncated:
        st.warning(f"⚠️ 데이터가 많아 일부만 사용됩니다. ({len(selected_data)}개 파일, 약 {total_tokens:,} 토큰)")
    
    return truncated


def display_chat_history():
    """채팅 히스토리 표시"""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def load_session(session_id: str):
    """이전 세션 로드"""
    # 현재 세션 저장
    if st.session_state.messages:
        save_chat_history(st.session_state.messages, st.session_state.current_session)
    
    # 새 세션 로드
    st.session_state.current_session = session_id
    st.session_state.messages = load_chat_history(session_id)


def rename_company(old_name, new_name):
    """회사명 변경"""
    try:
        companies = load_companies()
        if old_name not in companies:
            return False
        
        if new_name in companies:
            st.error(f"'{new_name}'은 이미 존재하는 회사명입니다")
            return False
        
        companies[new_name] = companies.pop(old_name)
        save_companies(companies)
        
        extracted_dir = Path("extracted_data")
        for file in extracted_dir.glob(f"{old_name}_*.json"):
            new_filename = file.name.replace(f"{old_name}_", f"{new_name}_", 1)
            new_path = extracted_dir / new_filename
            
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['company_name'] = new_name
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            file.unlink()
        
        old_dir = PDF_STORAGE_DIR / old_name
        new_dir = PDF_STORAGE_DIR / new_name
        if old_dir.exists():
            old_dir.rename(new_dir)
        
        return True
        
    except Exception as e:
        st.error(f"회사명 변경 실패: {e}")
        return False


def main():
    st.set_page_config(
        page_title="재무제표 비교 분석 챗봇",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 재무제표 비교 분석 챗봇")
    st.caption("회사별 재무제표를 업로드하고 비교 분석하세요 | 💾 영구 저장 | 🔄 자동 호환 | 🎯 스마트 컨텍스트 | 💬 대화 기록 자동 복구")

    init_session_state()

    # 세션 복구 메시지
    if "session_restored" in st.session_state and st.session_state.session_restored:
        if st.session_state.messages:
            st.success(f"✅ 이전 대화 기록이 자동으로 복구되었습니다. ({len(st.session_state.messages)}개 메시지)")
        del st.session_state.session_restored

    # 마이그레이션 메시지
    if "migration_message" in st.session_state:
        st.success(st.session_state.migration_message)
        del st.session_state.migration_message

    # 사이드바 (이하 동일 - 코드 생략)
    with st.sidebar:
        st.header("🏢 회사별 데이터 관리")

        if st.session_state.client is None:
            st.error("⚠️ API 키가 설정되지 않았습니다")
        else:
            st.success("✅ API 연결됨")

        companies = get_company_folders()
        total_files = sum([len(get_company_files(c)) for c in companies])
        st.caption(f"💾 {len(companies)}개 회사 | {total_files}개 파일")

        st.divider()

        # 새 회사 추가
        st.subheader("➕ 새 회사 추가")
        new_company = st.text_input("회사명 입력", placeholder="예: 우리회사")
        
        if new_company and st.button("회사 추가", use_container_width=True):
            if add_company(new_company):
                st.success(f"✅ '{new_company}' 추가됨")
                st.rerun()

        st.divider()

        # 파일 업로드
        st.subheader("📤 파일 업로드")
        
        if companies:
            selected_company = st.selectbox("회사 선택", [""] + companies)
            
            if selected_company:
                uploaded_files = st.file_uploader(
                    f"{selected_company}의 문서",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key=f"upload_{selected_company}"
                )
                
                if uploaded_files and st.button("📥 업로드 및 분석", use_container_width=True):
                    progress_bar = st.progress(0)
                    success_count = 0
                    
                    for idx, file in enumerate(uploaded_files):
                        status_text = st.empty()
                        status_text.text(f"분석 중: {file.name}")
                        
                        success, error = save_company_file(file, selected_company)
                        if success:
                            success_count += 1
                        else:
                            st.error(f"❌ {file.name}: {error}")
                        
                        progress_bar.progress((idx + 1) / len(uploaded_files))
                        status_text.empty()
                    
                    progress_bar.empty()
                    st.success(f"✅ {success_count}/{len(uploaded_files)}개 파일 분석 완료!")
                    st.rerun()

        st.divider()

        # 비교 분석 대상
        st.subheader("🔍 비교 분석 대상")
        
        if companies:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("전체 선택", use_container_width=True):
                    st.session_state.selected_companies = companies.copy()
                    st.rerun()
            with col2:
                if st.button("선택 해제", use_container_width=True):
                    st.session_state.selected_companies = []
                    st.rerun()
            
            for company in companies:
                files = get_company_files(company)
                is_selected = company in st.session_state.selected_companies
                
                if st.checkbox(
                    f"📁 {company} ({len(files)}개)",
                    value=is_selected,
                    key=f"check_{company}"
                ):
                    if company not in st.session_state.selected_companies:
                        st.session_state.selected_companies.append(company)
                else:
                    if company in st.session_state.selected_companies:
                        st.session_state.selected_companies.remove(company)

        st.divider()

        # 대화 히스토리
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
            st.caption(f"💾 저장된 대화: {len(sessions)}개")
            for session in sessions[:15]:  # 최근 15개 표시
                session_id = session["session_id"]
                msg_count = session["message_count"]

                col1, col2 = st.columns([3, 1])
                with col1:
                    try:
                        date_str = datetime.strptime(session_id, "%Y%m%d_%H%M%S").strftime("%m/%d %H:%M")
                    except:
                        date_str = session_id[:13]

                    # 현재 세션 표시
                    label = f"📝 {date_str} ({msg_count}건)"
                    if session_id == st.session_state.current_session:
                        label = f"🔴 {date_str} ({msg_count}건) [현재]"

                    if st.button(label, key=f"load_{session_id}", use_container_width=True):
                        load_session(session_id)
                        st.rerun()

                with col2:
                    if st.button("🗑️", key=f"del_session_{session_id}"):
                        delete_chat_history(session_id)
                        st.rerun()

    # 메인 영역
    if st.session_state.selected_companies:
        st.info(f"🔍 분석 대상: {', '.join(st.session_state.selected_companies)}")
    
    if not st.session_state.financial_context:
        st.session_state.financial_context = get_selected_companies_context()

    display_chat_history()

    if prompt := st.chat_input("질문하세요..."):
        if st.session_state.client is None:
            st.error("API 키가 설정되지 않았습니다")
            return

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("답변 생성 중..."):
                history = st.session_state.messages[:-1]
                smart_context = smart_context_selection(st.session_state.selected_companies, prompt)

                try:
                    response = st.session_state.client.ask(
                        question=prompt,
                        financial_context=smart_context,
                        conversation_history=history
                    )
                    st.markdown(response)
                except Exception as e:
                    if "too long" in str(e):
                        st.error("⚠️ 데이터가 많습니다. 특정 회사나 연도를 지정해주세요.")
                        response = "데이터가 많아 처리할 수 없습니다. 특정 회사나 연도를 지정해주세요."
                    else:
                        st.error(f"오류: {e}")
                        response = f"오류: {e}"
                    st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})
        save_chat_history(st.session_state.messages, st.session_state.current_session)


if __name__ == "__main__":
    main()
