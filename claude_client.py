import os
import time
from typing import List, Dict
from anthropic import Anthropic, RateLimitError, APIError
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """당신은 재무제표 분석 전문가입니다.
사용자가 업로드한 재무 데이터를 기반으로 질문에 정확하게 답변해주세요.

답변 시 다음 사항을 지켜주세요:
1. 제공된 재무 데이터에 기반하여 답변하세요
2. 데이터에 없는 내용은 추측하지 말고, 데이터에 없다고 명시하세요
3. 숫자를 인용할 때는 출처(연도, 항목명)를 함께 언급하세요
4. 재무 용어는 쉽게 설명해주세요
5. 필요시 계산 과정을 보여주세요
"""


class ClaudeClient:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 API 키를 설정해주세요."
            )
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
        self.max_retries = 3

    def ask(
        self,
        question: str,
        financial_context: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> str:
        """재무 데이터 컨텍스트와 함께 질문을 전송하고 답변을 받습니다."""

        # 시스템 프롬프트에 재무 데이터 컨텍스트 추가
        full_system = f"{SYSTEM_PROMPT}\n\n=== 재무 데이터 ===\n{financial_context}"

        # 메시지 구성
        messages = []

        # 이전 대화 히스토리 추가
        if conversation_history:
            messages.extend(conversation_history)

        # 현재 질문 추가
        messages.append({"role": "user", "content": question})

        # 재시도 로직
        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=full_system,
                    messages=messages
                )
                return response.content[0].text

            except RateLimitError as e:
                if attempt < self.max_retries - 1:
                    wait_time = (attempt + 1) * 30  # 30초, 60초, 90초
                    print(f"Rate limit 도달. {wait_time}초 후 재시도... ({attempt + 1}/{self.max_retries})")
                    time.sleep(wait_time)
                else:
                    return (
                        "⚠️ API 요청 한도에 도달했습니다.\n\n"
                        "**해결 방법:**\n"
                        "1. 1-2분 후 다시 시도해주세요\n"
                        "2. Anthropic Console에서 사용량을 확인하세요\n"
                        "3. 요금제 업그레이드를 고려해보세요"
                    )

            except APIError as e:
                return f"⚠️ API 오류가 발생했습니다: {str(e)}"

    def is_configured(self) -> bool:
        """API 키가 설정되어 있는지 확인합니다."""
        return os.getenv("ANTHROPIC_API_KEY") is not None
