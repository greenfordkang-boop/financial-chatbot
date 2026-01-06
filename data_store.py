import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "extracted")
HISTORY_DIR = os.path.join(os.path.dirname(__file__), "data", "history")


def ensure_data_dir():
    """데이터 디렉토리가 존재하는지 확인하고 없으면 생성합니다."""
    os.makedirs(DATA_DIR, exist_ok=True)


def save_extracted_data(data: Dict[str, Any], filename: str) -> str:
    """추출된 데이터를 JSON 파일로 저장합니다."""
    ensure_data_dir()

    # 메타데이터 추가
    data["extracted_at"] = datetime.now().isoformat()

    # 파일명에서 확장자 제거하고 .json 추가
    base_name = os.path.splitext(filename)[0]
    json_filename = f"{base_name}.json"
    filepath = os.path.join(DATA_DIR, json_filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return filepath


def load_extracted_data(filename: str) -> Optional[Dict[str, Any]]:
    """저장된 JSON 데이터를 로드합니다."""
    base_name = os.path.splitext(filename)[0]
    json_filename = f"{base_name}.json"
    filepath = os.path.join(DATA_DIR, json_filename)

    if not os.path.exists(filepath):
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def list_saved_files() -> List[str]:
    """저장된 모든 JSON 파일 목록을 반환합니다."""
    ensure_data_dir()
    files = []

    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".json"):
            files.append(filename)

    return sorted(files)


def delete_extracted_data(filename: str) -> bool:
    """저장된 데이터 파일을 삭제합니다."""
    base_name = os.path.splitext(filename)[0]
    json_filename = f"{base_name}.json"
    filepath = os.path.join(DATA_DIR, json_filename)

    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False


def get_all_data_context() -> str:
    """저장된 모든 데이터를 하나의 컨텍스트 문자열로 반환합니다."""
    from pdf_processor import get_financial_context

    files = list_saved_files()
    if not files:
        return "저장된 재무 데이터가 없습니다."

    all_contexts = []
    for filename in files:
        data = load_extracted_data(filename)
        if data:
            all_contexts.append(f"\n{'='*60}\n파일: {filename}\n{'='*60}")
            all_contexts.append(get_financial_context(data))

    return "\n".join(all_contexts)


# ============ 대화 히스토리 관련 함수 ============

def ensure_history_dir():
    """히스토리 디렉토리가 존재하는지 확인하고 없으면 생성합니다."""
    os.makedirs(HISTORY_DIR, exist_ok=True)


def save_chat_history(messages: List[Dict[str, str]], session_id: str = "default") -> str:
    """대화 히스토리를 JSON 파일로 저장합니다."""
    ensure_history_dir()

    history_data = {
        "session_id": session_id,
        "updated_at": datetime.now().isoformat(),
        "messages": messages
    }

    filepath = os.path.join(HISTORY_DIR, f"{session_id}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)

    return filepath


def load_chat_history(session_id: str = "default") -> List[Dict[str, str]]:
    """저장된 대화 히스토리를 로드합니다."""
    ensure_history_dir()
    filepath = os.path.join(HISTORY_DIR, f"{session_id}.json")

    if not os.path.exists(filepath):
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("messages", [])


def list_chat_sessions() -> List[Dict[str, Any]]:
    """저장된 모든 대화 세션 목록을 반환합니다."""
    ensure_history_dir()
    sessions = []

    for filename in os.listdir(HISTORY_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(HISTORY_DIR, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", filename[:-5]),
                    "updated_at": data.get("updated_at", ""),
                    "message_count": len(data.get("messages", []))
                })

    return sorted(sessions, key=lambda x: x["updated_at"], reverse=True)


def delete_chat_history(session_id: str) -> bool:
    """대화 히스토리를 삭제합니다."""
    filepath = os.path.join(HISTORY_DIR, f"{session_id}.json")

    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False
