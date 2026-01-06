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


def auto_migrate_legacy_data():
    """기존 데이터 자동 감지 및 마이그레이션"""
    extracted_dir = Path("extracted_data")
    if not extracted_dir.exists():
        return 0
    
    # 기존 형식 파일 찾기 (회사명_ 없는 파일)
    all_files = list(extracted_dir.glob("*.json"))
    legacy_files = []
    
    for file in all_files:
        filename = file.stem  # .json 제외
        # 회사명_파일명 형식이 아닌 파일 찾기
        if '_' not in filename or not filename.split('_')[0] in get_all_company_names():
            legacy_files.append(file)
    
    if not legacy_files:
        return 0
    
    # "기존데이터" 회사 자동 생성
    legacy_company = "기존데이터"
    companies = load_companies()
    
    if legacy_company not in companies:
        companies[legacy_company] = {
            "created_at": datetime.now().isoformat(),
            "file_count": 0,
            "auto_migrated": True
        }
        save_companies(companies)
    
    # 파일 변환
    migrated = 0
    for old_file in legacy_files:
        try:
            with open(old_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 이미 변환된 파일인지 확인
            if 'company_name' in data:
                continue
            
            original_name = old_file.name
            
            # 회사명 추가
            data['company_name'] = legacy_company
            data['original_filename'] = original_name.replace('.json', '')
            data['migrated_from_legacy'] = True
            
            # 새 파일명으로 저장
            new_filename = f"{legacy_company}_{original_name}"
            new_path = extracted_dir / new_filename
            
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            migrated += 1
            
            # 원본 파일은 백업 폴더로
            backup_dir = Path("backup_legacy_data")
            backup_dir.mkdir(exist_ok=True)
            old_file.rename(backup_dir / old_file.name)
            
        except Exception as e:
            st.error(f"마이그레이션 오류 ({old_file.name}): {e}")
    
    # 파일 개수 업데이트
    if migrated > 0:
        update_company_file_count(legacy_company)
    
    return migrated


def get_all_company_names():
    """모든 회사명 반환 (캐싱용)"""
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
    if "companies" not in st.session_state:
        # 앱 시작 시 자동 마이그레이션
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
    """PDF 저장 및 분석 (영구 저장)"""
    try:
        # 1. PDF를 영구 저장소에 저장
        pdf_path = save_pdf_permanently(uploaded_file, company_name)
        
        # 2. PDF 분석
        data = process_pdf(str(pdf_path))
        
        # 3. 분석 결과 저장
        data['company_name'] = company_name
        data['original_filename'] = uploaded_file.name
        data['stored_path'] = str(pdf_path)
        save_extracted_data(data, f"{company_name}_{uploaded_file.name}")
        
        # 4. 회사 파일 개수 업데이트
        update_company_file_count(company_name)
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def get_company_files(company_name):
    """회사의 파일 목록 반환 (extracted_data 기반)"""
    saved_files = list_saved_files()
    company_files = []
    
    for filename in saved_files:
        if filename.startswith(f"{company_name}_"):
            # "회사명_" 부분 제거
            original_name = filename[len(company_name)+1:]
            # .json 제거
            if original_name.endswith('.json'):
                original_name = original_name[:-5]
            company_files.append(original_name)
    
    return sorted(set(company_files))  # 중복 제거


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
        page_title="재무제표 비교 분석 챗봇",
        page_icon="📊",
        layout="wide"
    )

    st.title("📊 재무제표 비교 분석 챗봇")
    st.caption("회사별 재무제표를 업로드하고 비교 분석하세요 | 💾 데이터 영구 저장 | 🔄 기존 데이터 자동 호환")

    init_session_state()

    # 마이그레이션 메시지 표시
    if "migration_message" in st.session_state:
        st.success(st.session_state.migration_message)
        del st.session_state.migration_message

    # 사이드바: 회사 및 파일 관리
    with st.sidebar:
        st.header("🏢 회사별 데이터 관리")

        # API 키 상태 확인
        if st.session_state.client is None:
            st.error("⚠️ API 키가 설정되지 않았습니다")
            st.info("`.env` 파일 또는 Streamlit Secrets에 ANTHROPIC_API_KEY를 설정하세요")
        else:
            st.success("✅ API 연결됨")

        # 저장소 정보 표시
        companies = get_company_folders()
        total_files = sum([len(get_company_files(c)) for c in companies])
        st.caption(f"💾 {len(companies)}개 회사 | {total_files}개 파일 저장됨")

        st.divider()

        # 새 회사 추가
        st.subheader("➕ 새 회사 추가")
        new_company = st.text_input("회사명 입력", placeholder="예: 우리회사")
        
        if new_company and st.button("회사 추가", use_container_width=True):
            if add_company(new_company):
                st.success(f"✅ '{new_company}' 추가됨")
                st.rerun()
            else:
                st.warning("이미 존재하는 회사입니다")

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
                    key=f"upload_{selected_company}",
                    help="재무제표, 신용평가서, 규정집 등 모든 PDF 문서 가능"
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
                    
                    # 컨텍스트 자동 갱신
                    st.session_state.financial_context = get_selected_companies_context()
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
                
                # 기존데이터 표시
                company_display = company
                if company == "기존데이터":
                    company_display = f"{company} 🔄 (자동 마이그레이션)"
                
                if st.checkbox(
                    f"📁 {company_display} ({file_count}개 파일)",
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
                company_display = company
                if company == "기존데이터":
                    company_display = f"{company} 🔄"
                
                with st.expander(f"📁 {company_display}"):
                    files = get_company_files(company)
                    
                    if files:
                        # 기존데이터 안내 메시지
                        if company == "기존데이터":
                            st.info("💡 이전 버전에서 업로드한 파일입니다. 회사명을 변경하려면 '회사명 변경' 버튼을 클릭하세요.")
                            
                            # 회사명 변경 기능
                            new_name = st.text_input(
                                "새 회사명",
                                placeholder="예: 우리회사",
                                key=f"rename_{company}"
                            )
                            if new_name and st.button("회사명 변경", key=f"rename_btn_{company}"):
                                if rename_company("기존데이터", new_name):
                                    st.success(f"✅ '{new_name}'으로 변경됨")
                                    st.rerun()
                        
                        for file in files:
                            col1, col2 = st.columns([3, 1])
                            with col1:
                                st.text(file)
                            with col2:
                                if st.button("🗑️", key=f"del_{company}_{file}"):
                                    # PDF 파일 삭제
                                    delete_pdf_file(company, file)
                                    # 분석 데이터 삭제
                                    delete_extracted_data(f"{company}_{file}")
                                    # 파일 개수 업데이트
                                    update_company_file_count(company)
                                    st.success(f"✅ {file} 삭제됨")
                                    st.rerun()
                        
                        # 회사 전체 삭제
                        if st.button(f"🗑️ {company} 전체 삭제", key=f"del_company_{company}"):
                            # 모든 파일 삭제
                            for file in files:
                                delete_extracted_data(f"{company}_{file}")
                            
                            # 폴더 삭제
                            delete_company_folder(company)
                            
                            # 회사 목록에서 제거
                            companies_dict = load_companies()
                            if company in companies_dict:
                                del companies_dict[company]
                                save_companies(companies_dict)
                            
                            st.success(f"✅ {company} 전체 삭제됨")
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
    if "재무 데이터가 없습니다" in st.session_state.financial_context or "저장된 재무 데이터가 없습니다" in st.session_state.financial_context:
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
            
            ### 다양한 문서 유형
            - 재무제표, 신용평가서, 규정집, 계약서 등 모든 PDF 문서 분석 가능!
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


def rename_company(old_name, new_name):
    """회사명 변경"""
    try:
        # 1. companies.json 업데이트
        companies = load_companies()
        if old_name not in companies:
            return False
        
        if new_name in companies:
            st.error(f"'{new_name}'은 이미 존재하는 회사명입니다")
            return False
        
        companies[new_name] = companies.pop(old_name)
        save_companies(companies)
        
        # 2. extracted_data 파일명 변경
        extracted_dir = Path("extracted_data")
        for file in extracted_dir.glob(f"{old_name}_*.json"):
            new_filename = file.name.replace(f"{old_name}_", f"{new_name}_", 1)
            new_path = extracted_dir / new_filename
            
            # 파일 내용도 업데이트
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data['company_name'] = new_name
            with open(new_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 기존 파일 삭제
            file.unlink()
        
        # 3. PDF 폴더 이름 변경
        old_dir = PDF_STORAGE_DIR / old_name
        new_dir = PDF_STORAGE_DIR / new_name
        if old_dir.exists():
            old_dir.rename(new_dir)
        
        return True
        
    except Exception as e:
        st.error(f"회사명 변경 실패: {e}")
        return False


if __name__ == "__main__":
    main()
