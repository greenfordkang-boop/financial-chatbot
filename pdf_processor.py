import pdfplumber
from PyPDF2 import PdfReader
from typing import Dict, List, Any
import json


def extract_text_from_pdf(pdf_path: str) -> str:
    """PDF에서 전체 텍스트를 추출합니다."""
    reader = PdfReader(pdf_path)
    text_parts = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)

    return "\n\n".join(text_parts)


def extract_tables_from_pdf(pdf_path: str) -> List[Dict[str, Any]]:
    """PDF에서 모든 표(table)를 추출합니다."""
    tables_data = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()

            for table_idx, table in enumerate(tables):
                if table and len(table) > 0:
                    # 첫 번째 행을 헤더로 사용
                    headers = table[0] if table[0] else []
                    rows = table[1:] if len(table) > 1 else []

                    # 빈 셀 정리
                    headers = [h if h else f"열{i+1}" for i, h in enumerate(headers)]

                    table_dict = {
                        "page": page_num,
                        "table_index": table_idx + 1,
                        "headers": headers,
                        "rows": rows,
                        "row_count": len(rows)
                    }
                    tables_data.append(table_dict)

    return tables_data


def process_pdf(pdf_path: str) -> Dict[str, Any]:
    """PDF를 처리하여 텍스트와 표 데이터를 추출합니다."""
    result = {
        "source_file": pdf_path,
        "text_content": extract_text_from_pdf(pdf_path),
        "tables": extract_tables_from_pdf(pdf_path)
    }

    return result


def format_tables_for_context(tables: List[Dict[str, Any]]) -> str:
    """표 데이터를 LLM 컨텍스트용 문자열로 변환합니다."""
    if not tables:
        return "추출된 표가 없습니다."

    formatted_parts = []

    for table in tables:
        part = f"\n[표 - 페이지 {table['page']}, 표 {table['table_index']}]\n"
        headers = table['headers']
        part += " | ".join(str(h) for h in headers) + "\n"
        part += "-" * 50 + "\n"

        for row in table['rows']:
            row_str = " | ".join(str(cell) if cell else "" for cell in row)
            part += row_str + "\n"

        formatted_parts.append(part)

    return "\n".join(formatted_parts)


def get_financial_context(data: Dict[str, Any]) -> str:
    """추출된 데이터를 LLM에 전달할 컨텍스트로 변환합니다."""
    context_parts = []

    # 텍스트 컨텐츠
    if data.get("text_content"):
        context_parts.append("=== 문서 텍스트 내용 ===")
        context_parts.append(data["text_content"][:10000])  # 최대 10000자

    # 표 데이터
    if data.get("tables"):
        context_parts.append("\n=== 표 데이터 ===")
        context_parts.append(format_tables_for_context(data["tables"]))

    return "\n".join(context_parts)
