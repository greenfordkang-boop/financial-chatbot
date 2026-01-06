import streamlit as st
import tempfile
import os
from datetime import datetime
from pathlib import Path
import json
import shutil

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


# ========================================
# 영구 저장소 설정
# ========================================
PERSISTENT_DATA_DIR = Path("persistent_data")
PERSISTENT_DATA_DIR.mkdir(exist_ok=True)

COMPANIES_FILE = PERSISTENT_DATA_DIR / "companies.json"
PDF_STORAGE_DIR = PERSISTENT_DATA_DIR / "pdf_files"
PDF_STORAGE_DIR.mkdir(exist_ok=True)

# 토큰 제한
MAX_CONTEXT_TOKENS = 150000
CHARS_PER_TOKEN = 4


# ========================================
# 토큰 관리 함수
# ========================================
def estimate_tokens(text):
    """텍스트의 대략적인 토큰 수 추정"""
    if not text:
        return 0
    return len(str(text)) // CHARS_PER_TOKEN


def truncate_context(context, max_tokens=MAX_CONTEXT_TOKENS):
    """컨텍스트를 토큰 제한 내로 축약"""
    estimated_tokens = estimate_tokens(context)
    
    if estimated_tokens <= max_tokens:
        return context, False
    
    ratio = max_tokens / estimated_tokens
    max_chars = int(len(context) * ratio * 0.95)
    
    truncated = context[:max_chars]
    truncated += "\n\n... [내용이 너무 길어 일부만 표시됩니다.]"
    
    return truncated, True


# ========================================
# 기존 데이터 자동 마이그레이션
# ========================================
def auto_migrate_legacy_data():
    """기존 데이터 자동 감지 및 변환"""
    extracted_dir = Path("extracted_data")
    if not extracted_dir.exists():
        return 0
    
    all_files = list(extracted_dir.glob("*.json"))
    legacy_files = []
    
    existing_companies = get_all_company_names()
    
    for file in all_files:
        filename = file.stem
        # 회사명_ 형식이 아니거나, 알 수 없는 회사명
        if '_' not in filename:
            legacy_files.append(file)
        else:
            company_part = filename.split('_')[0]
            if company_part not in existing_companies:
                legacy_files.append(file)
    
    if not legacy_files:
        return 0
    
    # "기존데이터" 회사 생성
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
            
            # 이미 company_name 있으면 스킵
            if 'company_name' in data and data['company_name'] == legacy_company:
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
            
            # 원본 백업
            backup_dir = Path("backup_legacy_data")
            backup_dir.mkdir(exist_ok=True)
            if old_file.exists():
                shutil.copy2(old_file, backup_dir / old_file.name)
                old_file.unlink()
            
        except Exception as e:
            st.error(f"마이그레이션 오류: {old_file.name} - {e}")
    
    if migrated > 0:
        update_company_file_count(legacy_company)
    
    return migrated


# ========================================
# 회사 관리 함수
# ========================================
def get_all_company_names():
    """모든 회사명 반환"""
    companies = load_companies()
    return list(companies.keys())


def load_companies():
    """회사 목록 로드"""
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


def get_company_folders():
    """저장된 회사 목록"""
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
        return True
    return False


def update_company_file_count(company_name):
    """파일 개수 업데이트"""
    companies = load_companies()
    if company_name in companies:
        files = get_company_files(company_name)
        companies[company_name]["file_count"] = len(files)
        save_companies(companies)


def rename_company(old_name, new_name):
    """회사명 변경"""
    try:
        companies = load_companies()
        if old_name not in companies or new_name in companies:
            return False
        
        companies[new_name] = companies.pop(old_name)
        save_companies(companies)
        
        # 파일명 변경
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
        
        # PDF 폴더 변경
        old_dir = PDF_STORAGE_DIR / old_name
        new_dir = PDF_STORAGE_DIR / new_name
        if old_dir.exists():
            old_dir.rename(new_dir)
        
        return True
    except Exception as e:
        st.error(f"회사명 변경 실패: {e}")
        return False


# ========================================
# 파일 관리 함수
# ========================================
def save_pdf_permanently(uploaded_file, company_name):
    """PDF 영구 저장"""
    company_dir = PDF_STORAGE_DIR / company_name
    company_dir.mkdir(exist_ok=True)
    
    file_path = company_dir / uploaded_file.name
    with open(file_path, 'wb') as f:
        f.write(uploaded_file.getvalue())
    
    return file_path


def save_company_file(uploaded_file, company_name):
    """PDF 저장 및 분석"""
    try:
        # PDF 저장
        pdf_path = save_pdf_permanently(uploaded_file, company_name)
        
        # PDF 분석
        data = process_pdf(str(pdf_path))
        
        data['company_name'] = company_name
        data['original_filename'] = uploaded_file.name
        data['stored_path'] = str(pdf_path)
        
        # 토큰 경고
        estimated_tokens = estimate_tokens(data.get('text', ''))
        if estimated_tokens > 50000:
            st.warning(f"⚠️ 큰 파일: 약 {estimated_tokens:,} 토큰")
        
        save_extracted_data(data, f"{company_name}_{uploaded_file.name}")
        update_company_file_count(company_name)
        
        return True, None
    except Exception as e:
        return False, str(e)


def get_company_files(company_name):
    """회사의 파일 목록"""
    saved_files = list_saved_files()
    company_files = []
    
    for filename in saved_files:
        if filename.startswith(f"{company_name}_"):
            original = filename[len(company_name)+1:]
            if original.endswith('.json'):
                original = original[:-5]
            company_files.append(original)
    
    return sorted(set(company_files))


def delete_pdf_file(company_name, filename):
    """PDF 삭제"""
    file_path = PDF_STORAGE_DIR / company_name / filename
    if file_path.exists():
        file_path.unlink()


def delete_company_folder(company_name):
    """회사 폴더 삭제"""
    company_dir = PDF_STORAGE_DIR / company_name
    if company_dir.exists():
        shutil.rmtree(company_dir)


# ========================================
# 컨텍스트 관리
# ========================================
def get_selected_companies_context():
    """선택된 회사들의 데이터"""
    if not st.session_state.selected_companies:
        context = get_all_data_context()
        truncated, _ = truncate_context(context)
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
        return "선택된 회사의 데이터가 없습니다."
    
    context_parts = []
    for data in selected_data:
        company_name = data.get('company_name', '알 수 없음')
        filename = data.get('original_filename', '')
        context_parts.append(f"\n\n=== {company_name} - {filename} ===\n")
        context_parts.append(data.get('text', ''))
    
    full_context = "\n".join(context_parts)
    truncated, was_truncated = truncate_context(full_context)
    
    if was_truncated:
        st.warning(f"⚠️ 데이터가 많아 일부만 사용됩니다.")
    
    return truncated


# ========================================
# 세션 관리
# ========================================
def init_session_state():
    """세션 초기화 - 자동 복구 포함"""
    if "current_session" not in st.session_state:
        # 최근 세션 자동 복구
        sessions = list_chat_sessions()
        if sessions:
            latest = sessions[0]["session_id"]
            st.session_state.current_session = latest
            st.session_state.session_restored = True
        else:
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
    
    if "companies" not in st.session_state:
        # 자동 마이그레이션
        migrated_count = auto_migrate_legacy_data()
        if migrated_count > 0:
            st.session_state.migration_message = f"✅ 기존 데이터 {migrated_count}개를 '기존데이터' 회사로 자동 이동했습니다."
        st.session_state.companies = load_companies()


def display_chat_history():
    """채팅 히스토리 표시"""
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])


def load_session(session_id: str):
    """세션 로드"""
    if st.session_state.messages:
        save_chat_history(st.session_state.messages, st.session_state.current_session)
    
    st.session_state.current_session = session_id
    st.session_state.messages = load_chat_history(session_id)


# ========================================
# 메인 앱
# ========================================
def main():
    st.set_page_config(
        page_title="재무제표 비교 분석 챗봇",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 재무제표 비교 분석 챗봇")
    st.caption("💾 영구 저장 | 🔄 자동 호환 | 🎯 스마트 컨텍스트 | 💬 대화 자동 복구")

    init_session_state()

    # 복구 메시지
    if "session_restored" in st.session_state and st.session_state.session_restored:
        if st.session_state.messages:
            st.success(f"✅ 이전 대화가 자동 복구되었습니다. ({len(st.session_state.messages)}개)")
        del st.session_state.session_restored

    if "migration_message" in st.session_state:
        st.success(st.session_state.migration_message)
        del st.session_state.migration_message

    # 사이드바
    with st.sidebar:
        st.header("🏢 회사별 데이터 관리")

        # API 상태
        if st.session_state.client is None:
            st.error("⚠️ API 키가 설정되지 않았습니다")
        else:
            st.success("✅ API 연결됨")

        # 통계
        companies = get_company_folders()
        total_files = sum([len(get_company_files(c)) for c in companies])
        st.caption(f"💾 {len(companies)}개 회사 | {total_files}개 파일")

        st.divider()

        # 회사 추가
        st.subheader("➕ 새 회사 추가")
        new_company = st.text_input("회사명", placeholder="예: 우리회사")
        
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
                
                if uploaded_files and st.button("📥 업로드", use_container_width=True):
                    progress = st.progress(0)
                    success_count = 0
                    
                    for idx, file in enumerate(uploaded_files):
                        status = st.empty()
                        status.text(f"분석 중: {file.name}")
                        
                        ok, err = save_company_file(file, selected_company)
                        if ok:
                            success_count += 1
                        else:
                            st.error(f"❌ {file.name}: {err}")
                        
                        progress.progress((idx + 1) / len(uploaded_files))
                        status.empty()
                    
                    progress.empty()
                    st.success(f"✅ {success_count}/{len(uploaded_files)}개 완료!")
                    st.rerun()
        else:
            st.info("먼저 회사를 추가하세요")

        st.divider()

        # 비교 대상 선택
        st.subheader("🔍 비교 분석 대상")
        
        if companies:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("전체", use_container_width=True):
                    st.session_state.selected_companies = companies.copy()
                    st.rerun()
            with col2:
                if st.button("해제", use_container_width=True):
                    st.session_state.selected_companies = []
                    st.rerun()
            
            for company in companies:
                files = get_company_files(company)
                is_sel = company in st.session_state.selected_companies
                
                display_name = company
                if company == "기존데이터":
                    display_name = f"{company} 🔄"
                
                if st.checkbox(f"📁 {display_name} ({len(files)}개)", value=is_sel, key=f"c_{company}"):
                    if company not in st.session_state.selected_companies:
                        st.session_state.selected_companies.append(company)
                else:
                    if company in st.session_state.selected_companies:
                        st.session_state.selected_companies.remove(company)
            
            if st.button("🔄 갱신", use_container_width=True):
                st.session_state.financial_context = get_selected_companies_context()
                st.success("✅ 갱신 완료!")

        st.divider()

        # 파일 관리
        st.subheader("📋 저장된 파일")
        
        if companies:
            for company in companies:
                display_name = f"📁 {company}"
                if company == "기존데이터":
                    display_name = f"📁 {company} 🔄"
                
                with st.expander(display_name):
                    files = get_company_files(company)
                    
                    if files:
                        # 회사명 변경
                        if company == "기존데이터":
                            st.info("💡 이전 버전 파일입니다")
                            new_name = st.text_input("새 회사명", placeholder="우리회사", key=f"rn_{company}")
                            if new_name and st.button("변경", key=f"rnb_{company}"):
                                if rename_company(company, new_name):
                                    st.success(f"✅ '{new_name}'으로 변경")
                                    st.rerun()
                        
                        # 파일 목록
                        for file in files:
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.text(file)
                            with col2:
                                if st.button("🗑️", key=f"d_{company}_{file}"):
                                    delete_pdf_file(company, file)
                                    delete_extracted_data(f"{company}_{file}")
                                    update_company_file_count(company)
                                    st.rerun()
                        
                        # 전체 삭제
                        if st.button(f"🗑️ {company} 전체", key=f"da_{company}"):
                            for f in files:
                                delete_extracted_data(f"{company}_{f}")
                            delete_company_folder(company)
                            
                            comps = load_companies()
                            if company in comps:
                                del comps[company]
                                save_companies(comps)
                            st.rerun()
                    else:
                        st.caption("파일 없음")

        st.divider()

        # 대화 히스토리
        st.subheader("💬 대화 히스토리")
        st.caption(f"현재: {st.session_state.current_session}")

        if st.button("➕ 새 대화", use_container_width=True):
            if st.session_state.messages:
                save_chat_history(st.session_state.messages, st.session_state.current_session)
            st.session_state.current_session = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.session_state.messages = []
            st.rerun()

        sessions = list_chat_sessions()
        if sessions:
            st.caption(f"💾 {len(sessions)}개 저장됨")
            for sess in sessions[:15]:
                sid = sess["session_id"]
                cnt = sess["message_count"]

                col1, col2 = st.columns([3, 1])
                with col1:
                    try:
                        dt = datetime.strptime(sid, "%Y%m%d_%H%M%S").strftime("%m/%d %H:%M")
                    except:
                        dt = sid[:13]

                    label = f"📝 {dt} ({cnt}건)"
                    if sid == st.session_state.current_session:
                        label = f"🔴 {dt} ({cnt}건)"

                    if st.button(label, key=f"l_{sid}", use_container_width=True):
                        load_session(sid)
                        st.rerun()

                with col2:
                    if st.button("🗑️", key=f"ds_{sid}"):
                        delete_chat_history(sid)
                        st.rerun()

    # 메인 영역
    if st.session_state.selected_companies:
        st.info(f"🔍 분석 대상: {', '.join(st.session_state.selected_companies)}")
    
    if not st.session_state.financial_context:
        st.session_state.financial_context = get_selected_companies_context()

    if "데이터가 없습니다" in st.session_state.financial_context:
        st.warning("📌 먼저 회사를 추가하고 문서를 업로드하세요")
        
        with st.expander("💡 사용 팁"):
            st.markdown("""
            ### 효율적인 질문
            - **연도 지정**: "2023년 매출액은?"
            - **회사 선택**: 1-2개만 선택
            - **구체적**: "전체" 대신 "영업이익"
            
            ### 지원 문서
            재무제표, 신용평가서, 규정집, 계약서 등 모든 PDF!
            """)

    display_chat_history()

    # 채팅 입력
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
                context = get_selected_companies_context()

                try:
                    response = st.session_state.client.ask(
                        question=prompt,
                        financial_context=context,
                        conversation_history=history
                    )
                    st.markdown(response)
                except Exception as e:
                    if "too long" in str(e):
                        st.error("⚠️ 데이터가 많습니다. 특정 회사나 연도를 지정해주세요.")
                        response = "데이터가 많습니다. 특정 회사나 연도를 지정해주세요."
                    else:
                        st.error(f"오류: {e}")
                        response = f"오류: {e}"
                    st.markdown(response)

        st.session_state.messages.append({"role": "assistant", "content": response})
        save_chat_history(st.session_state.messages, st.session_state.current_session)


if __name__ == "__main__":
    main()
