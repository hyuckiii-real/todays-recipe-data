import os
import json
import time
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 한국 시간(KST) 기준 오늘 날짜 및 요일 계산
kst = timezone(timedelta(hours=9))
now_kst = datetime.now(kst)
today_str = now_kst.strftime("%Y-%m-%d")

weekday_themes = {
    0: "월요일 (퇴근 후 10분 컷 초간단 한 그릇)",
    1: "화요일 (집에 있는 기본 재료로 뚝딱 만드는 집밥)",
    2: "수요일 (지친 수요일 밤, 따뜻한 국물이나 볶음 요리)",
    3: "목요일 (편의점·마트 5분 장보기로 만드는 별미)",
    4: "금요일 (불금에 기분 내기 좋은 야식·안주 겸용 요리)",
    5: "토요일 (주말 점심에 느긋하게 즐기는 브런치·면 요리)",
    6: "일요일 (일요일 저녁, 속 편하고 든든한 마무리 요리)",
}
today_theme = weekday_themes[now_kst.weekday()]

# 기존 생성 내역 불러오기 (메뉴 중복 방지)
archive_path = "archive.json"
archive = []
if os.path.exists(archive_path):
    try:
        with open(archive_path, "r", encoding="utf-8") as f:
            archive = json.load(f)
    except Exception as exc:
        raise RuntimeError("archive.json 읽기 실패: 이전 메뉴 기록을 보호하기 위해 생성 중단") from exc

def normalize_menu(value):
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"[^\w가-힣]", "", value)

# 날짜 확인: 복구 실행이나 수동 재실행에서는 이미 만든 콘텐츠를 건드리지 않는다.
if any(item.get("date") == today_str for item in archive):
    print(f"[{today_str}] 오늘 메뉴가 이미 있어 생성하지 않습니다.")
    raise SystemExit(0)

past_menus = [item.get("menu_name", "") for item in archive if item.get("menu_name")]
used_menus = {normalize_menu(name) for name in past_menus}

class IngredientItem(BaseModel):
    name: str = Field(description="재료명과 분량 (예: 대파 1/2대, 계란 2알)")
    category: str = Field(description="'장보기 재료' 또는 '집에 있을 기본 재료' 중 하나")
    substitute: str = Field(description="이 재료가 없을 때 쓸 수 있는 현실적인 대체 재료 팁 (예: 대파가 없다면 쪽파나 양파 1/4개로도 충분해요!)")

class CookingStep(BaseModel):
    step_number: int = Field(description="단계 번호 (1부터 시작)")
    title: str = Field(description="단계 핵심 요약 (예: 재료 썰기, 양념장 섞기)")
    instruction: str = Field(description="요리 초보도 바로 따라 할 수 있는 친절하고 구체적인 설명 (1~2문장)")
    timer_seconds: int = Field(description="이 단계에서 타이머가 필요하면 초 단위 숫자 (예: 3분이면 180), 불 앞 대기가 필요 없으면 0")

class DailyRecipe(BaseModel):
    date: str = Field(description="오늘 날짜 (YYYY-MM-DD)")
    theme_badge: str = Field(description="상황/분위기 배지 (예: 10분 컷 혼밥, 퇴근길 5분 장보기)")
    menu_name: str = Field(description="오늘 따라 해볼 요리 이름 (한국에서 실제로 해먹기 좋은 현실적인 메뉴)")
    emoji: str = Field(description="요리를 대표하는 음식 이모지 1개")
    cook_time_minutes: int = Field(description="총 예상 조리 시간 (분 단위, 10~25분 이내 권장)")
    difficulty: str = Field(description="난이도 ('왕초보 가능' 또는 '쉬움')")
    friend_message: str = Field(description="요리 잘하는 친구가 옆에서 말을 거는 듯한 따뜻하고 친근한 추천 한마디 (2문장 이내)")
    ingredients: list[IngredientItem] = Field(description="필수 재료 및 기본 재료 목록 (총 4~7개 내외)")
    steps: list[CookingStep] = Field(description="따라 하기 쉬운 3~5단계 조리 순서")
    today_mission: str = Field(description="오늘의 가벼운 요리 미션 문구 (예: 오늘 저녁, 배달 앱 켜기 전에 15분만 투자해서 직접 만들어 보세요!)")

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

prompt = f"""
당신은 자취생과 직장인에게 '오늘 당장 부담 없이 따라 해볼 수 있는 현실적인 요리'를 매일 딱 1가지씩 추천하는 다정한 요리 친구입니다.

오늘 날짜: {today_str}
오늘의 테마: {today_theme}
이미 추천했던 메뉴 목록 (절대 중복 금지): {", ".join(past_menus) if past_menus else "없음"}

[작성 원칙]
1. 거창한 레스토랑 요리나 구하기 힘든 향신료가 들어가는 요리는 절대 피하세요.
2. 동네 마트나 편의점에서 5분 만에 살 수 있는 재료, 혹은 냉장고에 흔히 있는 재료로 10~20분 내에 완성할 수 있는 메뉴를 고르세요.
3. 모든 재료에는 '없다면?' 하고 눌러볼 수 있는 실질적인 대체 재료 팁(substitute)을 꼭 적어주세요.
4. 조리 단계(steps)는 손에 물이 묻은 상태에서도 한눈에 읽히도록 짧고 명확하게 쓰고, 볶기·끓이기·익히기 단계에는 알맞은 timer_seconds(초)를 넣어주세요.
5. date 필드는 반드시 "{today_str}"로 설정하세요.
"""

# 서버 과부하(503) 대비 느긋한 재시도 로직 (최대 5회)
response = None
max_retries = 5
for attempt in range(1, max_retries + 1):
    try:
        print(f"[{attempt}/{max_retries}] 오늘의 요리 생성 요청 중...")
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=DailyRecipe,
                temperature=0.8,
            ),
        )
        break
    except Exception as e:
        print(f"[{attempt}/{max_retries}] 일시적 오류 발생: {e}")
        if attempt == max_retries:
            raise
        wait_seconds = attempt * 30  # 30초, 60초, 90초, 120초 대기
        print(f"서버가 안정될 때까지 {wait_seconds}초 기다렸다가 다시 시도합니다...")
        time.sleep(wait_seconds)

recipe_data = json.loads(response.text)
# AI 지시만으로 중복 방지를 보장할 수 없으므로 저장 직전에 재검증한다.
for duplicate_attempt in range(3):
    name = recipe_data.get("menu_name", "")
    if name and normalize_menu(name) not in used_menus:
        break
    if duplicate_attempt == 2:
        raise RuntimeError(f"이미 사용한 메뉴가 반복 생성되어 저장 중단: {name}")
    print(f"중복 메뉴 발견: {name}. 다른 메뉴 재생성 ({duplicate_attempt + 1}/2)")
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt + f"\n중복으로 거절된 메뉴: {name}. 반드시 완전히 다른 메뉴를 골라주세요.",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=DailyRecipe,
            temperature=0.9,
        ),
    )
    recipe_data = json.loads(response.text)
recipe_data["date"] = today_str

with open("today.json", "w", encoding="utf-8") as f:
    json.dump(recipe_data, f, ensure_ascii=False, indent=2)

# archive.json 업데이트 (같은 날짜 덮어쓰기 방지 후 최신순 유지)
archive = [item for item in archive if item.get("date") != today_str]
archive.append(recipe_data)
with open("archive.json", "w", encoding="utf-8") as f:
    json.dump(archive, f, ensure_ascii=False, indent=2)

print(f"생성 완료: {recipe_data['menu_name']}")
