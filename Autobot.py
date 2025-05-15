import os
import hashlib
import threading
import time
from datetime import datetime
import logging # 로깅 모듈 추가

import pytz
import gspread
from flask import Flask
from oauth2client.service_account import ServiceAccountCredentials # type: ignore
from dotenv import load_dotenv
import telebot # type: ignore
from gspread.exceptions import APIError
import re # re 모듈 추가

# ─────── MarkdownV2 이스케이프 헬퍼 함수 ──────────────
def escape_markdownv2(text):
    """
    MarkdownV2에서 예약된 문자를 이스케이프 처리합니다.
    """
    if text is None:
        return ''
    text = str(text)
    # MarkdownV2에서 예약된 모든 문자 목록
    # _, *, [, ], (, ), ~, `, >, #, +, -, =, |, {, }, ., !
    # 정규 표현식을 사용하여 이 문자들을 찾고 앞에 '\'를 붙여줍니다.
    # '['나 ']' 같은 문자는 정규식 패턴 안에서 특별한 의미를 가질 수 있으므로 패턴 자체를 raw string으로 사용하거나 이중 이스케이프가 필요할 수 있습니다.
    # 여기서는 간단하게 각 문자에 대해 replace 하는 방식을 사용합니다.
    # 더 견고한 처리를 위해 re.sub을 사용할 수도 있습니다.
    
    # 간단한 replace 방식 (일부 복잡한 경우에 문제될 수 있으나 대부분의 이름/문장에서 작동)
    # for char in r'_*[]()~`>#+-=|{}.!':
    #    text = text.replace(char, f'\\{char}')
    # return text

    # re.sub 방식 (더 강력)
    # 패턴 내에서 정규식 특별 문자는 이스케이프 해줘야 합니다 (\, [, ], (, ), {, }, |, ., +, *, ?, ^, $).
    # 우리는 예약 문자 자체를 찾는 패턴을 만듭니다.
    reserved_chars_pattern = r'([_*\[\]()~`>#\+\-=\|\{\}\.!])'
    # 찾은 각 문자를 '\'와 그 문자(\1)로 치환
    return re.sub(reserved_chars_pattern, r'\\\1', text)

# ─── 로깅 설정 ────────────────────────────────────────────────────────────────
# 기본 로깅 레벨은 INFO, 필요시 DEBUG로 변경하여 더 자세한 로그 확인 가능
logging.basicConfig(
    level=logging.INFO, # INFO 레벨 이상 로그 출력 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__) # 현재 모듈에 대한 로거 생성

# ─── 환경 변수 로드 ────────────────────────────────────────────────────────────
load_dotenv()
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Sheet1")
BASE_TOKEN      = os.getenv("TELEGRAM_TOKEN")
PORT            = int(os.getenv("PORT", 5000))

# ─── Flask 앱 (헬스체크) ────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/", methods=["GET"])
def root():
    logger.info("Health check '/' endpoint called.")
    return "OK", 200

@app.route("/ping", methods=["GET"])
def ping():
    logger.info("Health check '/ping' endpoint called.")
    return "pong", 200

@app.route("/favicon.ico")
def favicon():
    return "", 204

# ─── 시간대 설정 ───────────────────────────────────────────────────────────────
KST = pytz.timezone("Asia/Seoul")

# ─── 캐시 변수 ─────────────────────────────────────────────────────────────────
last_sheet_hash = None
welcome_list    = []  # 입장 시 환영 메시지
schedule_list   = []  # 요일·시간 스케줄

# ─── 헬퍼 함수 ─────────────────────────────────────────────────────────────────
def get_sheet_hash(values):
    flat_list = []
    for row in values:
        for item in row:
            flat_list.append(str(item)) # 모든 아이템을 문자열로 변환하여 일관성 유지
    flat_string = "".join(flat_list)
    return hashlib.md5(flat_string.encode('utf-8')).hexdigest()


def convert_weekday_kor_to_eng(kor):
    m = {
        "월요일": "monday", "화요일": "tuesday", "수요일": "wednesday",
        "목요일": "thursday", "금요일": "friday", "토요일": "saturday",
        "일요일": "sunday", "입장시": "on_join"
    }
    return m.get(str(kor).strip(), "").lower() # 입력값을 문자열로 변환 후 처리

# ─── 시트 데이터 로드 & 캐싱 (예외 처리 포함) ─────────────────────────────────
def load_configs():
    global last_sheet_hash, welcome_list, schedule_list
    logger.info("[LOAD_CONFIGS] 설정 로드 시도...")

    if not SPREADSHEET_URL or not BASE_TOKEN:
        logger.error("[LOAD_CONFIGS] SPREADSHEET_URL 또는 TELEGRAM_TOKEN 환경변수가 설정되지 않았습니다.")
        return

    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # google_credentials.json 파일이 현재 작업 디렉토리에 있어야 함
        # Render 등에서는 Secret File 기능을 사용하여 업로드하고 경로를 지정해야 할 수 있음
        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
        if not os.path.exists(creds_path):
            logger.error(f"[LOAD_CONFIGS] Google Credentials 파일({creds_path})을 찾을 수 없습니다.")
            return

        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        client = gspread.authorize(creds)

        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = spreadsheet.worksheet(SPREADSHEET_NAME)

        values = sheet.get_all_values() # 시트 전체 값 가져오기 (헤더 포함)
        current_hash = get_sheet_hash(values)

        if current_hash == last_sheet_hash:
            logger.info("[LOAD_CONFIGS] 시트 내용 변경 없음. 기존 설정 사용.")
            return

        logger.info(f"[LOAD_CONFIGS] 시트 변경 감지 (이전 해시: {last_sheet_hash}, 새 해시: {current_hash}). 설정 다시 로드 중...")
        last_sheet_hash = current_hash

        data = sheet.get_all_records() # 헤더를 키로 사용하는 딕셔너리 리스트 반환
        
        # 리스트 초기화 전에 임시 리스트 사용 (오류 발생 시 이전 데이터 유지 목적)
        temp_welcome_list = []
        temp_schedule_list = []

        for row_num, row in enumerate(data, start=2): # start=2 (헤더 제외한 실제 데이터 행 번호)
            try:
                # 필수 컬럼 확인
                send_day_raw = row.get("보낼 요일")
                group_id_raw = row.get("그룹방 ID")
                message_raw = row.get("보낼 메세지")

                if send_day_raw is None or group_id_raw is None or message_raw is None:
                    logger.warning(f"[LOAD_CONFIGS] {row_num}행: 필수 컬럼('보낼 요일', '그룹방 ID', '보낼 메세지') 중 누락된 값이 있어 건너<0xEB><0xA9>니다: {row}")
                    continue
                
                wd = convert_weekday_kor_to_eng(send_day_raw)
                if not wd: # 변환 실패 시 (예: 오타)
                    logger.warning(f"[LOAD_CONFIGS] {row_num}행: '보낼 요일' 값('{send_day_raw}')을 변환할 수 없습니다. 건너<0xEB><0xA9>니다.")
                    continue

                try:
                    # 그룹방 ID는 보통 음수이므로, 문자열 처리 시 주의
                    chat_id_str = str(group_id_raw).strip()
                    if not chat_id_str.startswith("-100") and chat_id_str.isdigit():
                         cid = int("-100" + chat_id_str)
                    else:
                         cid = int(chat_id_str) # 이미 -100으로 시작하거나 다른 형식의 ID일 경우 그대로 사용
                except ValueError:
                    logger.warning(f"[LOAD_CONFIGS] {row_num}행: '그룹방 ID' 값('{group_id_raw}')을 정수로 변환할 수 없습니다. 건너<0xEB><0xA9>니다.")
                    continue
                
                tid_raw = row.get("토픽 ID", "0") # 기본값을 문자열 "0"으로
                try:
                    tid = int(str(tid_raw).strip()) if str(tid_raw).strip() else 0
                except ValueError:
                    logger.warning(f"[LOAD_CONFIGS] {row_num}행: '토픽 ID' 값('{tid_raw}')을 정수로 변환할 수 없습니다. 기본값 0을 사용합니다.")
                    tid = 0
                
                msg = str(message_raw) # 메시지는 항상 문자열로
                send_time_raw = row.get("보낼 시간", "").strip()

                if wd == "on_join":
                    temp_welcome_list.append({
                        "chat_id": cid,
                        "topic_id": tid,
                        "message": msg,
                        "row_num": row_num # 디버깅용 행 번호 추가
                    })
                else:
                    if not send_time_raw: # 예약 메시지인데 시간이 없으면
                        logger.warning(f"[LOAD_CONFIGS] {row_num}행: 예약 메시지({wd})에 '보낼 시간'이 지정되지 않았습니다. 건너<0xEB><0xA9>니다.")
                        continue
                    temp_schedule_list.append({
                        "weekday": wd,
                        "time": send_time_raw,
                        "chat_id": cid,
                        "topic_id": tid,
                        "message": msg,
                        "row_num": row_num # 디버깅용 행 번호 추가
                    })
            except Exception as e:
                logger.error(f"[LOAD_CONFIGS] {row_num}행 데이터 처리 중 예기치 않은 오류 발생: {row}, 오류: {e}", exc_info=True)


        welcome_list = temp_welcome_list
        schedule_list = temp_schedule_list

        logger.info(f"[LOAD_CONFIGS] 로드된 환영 메시지 수: {len(welcome_list)}")
        if welcome_list:
            logger.debug(f"[LOAD_CONFIGS] 첫번째 환영 메시지 예시: {welcome_list[0]}")
        logger.info(f"[LOAD_CONFIGS] 로드된 스케줄 수: {len(schedule_list)}")
        if schedule_list:
            logger.debug(f"[LOAD_CONFIGS] 첫번째 스케줄 예시: {schedule_list[0]}")

    except APIError as e:
        logger.warning(f"[LOAD_CONFIGS] Google Sheets APIError: {e}. 다음 주기에 재시도합니다.")
    except Exception as e:
        logger.error(f"[LOAD_CONFIGS] 설정 로드 중 심각한 오류 발생: {e}", exc_info=True)


# ─── TeleBot 생성 & 환영 핸들러 등록 ───────────────────────────────────────────
if not BASE_TOKEN:
    logger.critical("TELEGRAM_TOKEN 환경 변수가 설정되지 않았습니다. 봇을 시작할 수 없습니다.")
    # 여기서 프로그램을 종료하거나, 적절한 오류 처리를 해야 합니다.
    # 예: exit(1) 또는 raise ValueError(...)
    # 지금은 다음 코드가 실행되지 않도록 bot 객체 생성을 조건부로 만듭니다.
    bot = None
else:
    bot = telebot.TeleBot(BASE_TOKEN, threaded=False)


if bot: # bot 객체가 성공적으로 생성된 경우에만 핸들러 등록
    @bot.message_handler(content_types=['new_chat_members'])
    def handle_new_members(message):
        if not message.new_chat_members:
            return

        logger.info(f"[NEW_MEMBER] 채팅 ID {message.chat.id} 에 새 멤버 {len(message.new_chat_members)}명 감지.")
        for new_user in message.new_chat_members:
            user_info = f"{new_user.first_name}"
            if new_user.last_name:
                user_info += f" {new_user.last_name}"
            if new_user.username:
                user_info += f" (@{new_user.username})"

            logger.info(f"[NEW_MEMBER] 처리 중인 새 멤버: {user_info} (ID: {new_user.id})")

            for cfg_idx, cfg in enumerate(welcome_list):
                if message.chat.id == cfg["chat_id"]:
                    logger.debug(f"[NEW_MEMBER] 채팅 ID {message.chat.id}에 대한 환영 설정 {cfg_idx} (원본 행: {cfg.get('row_num', 'N/A')}) 발견.")
                    try:
                        # 메시지에 사용자 이름 적용 (format 방식 대신 f-string 유사 방식 고려)
                        # 단순 new_user 객체 전체를 format에 넘기면 오류 발생 가능성이 높음
                        # 필요한 속성만 명시적으로 사용: {new_user.first_name}, {new_user.username} 등
                        # 여기서는 간단히 {new_user} 플레이스홀더를 사용자 이름으로 대체
                        personalized_message = cfg["message"].replace("{new_user}", user_info)
                        # 만약 시트에 {new_user.first_name} 같은 구체적인 형식을 쓴다면,
                        # personalized_message = cfg["message"].format(new_user=new_user) # 와 같이 사용 가능
                        # 다만, new_user 객체에 해당 속성이 없을 경우 오류 발생하므로 주의
                        
                    except Exception as e:
                        logger.error(f"[NEW_MEMBER] 메시지 포맷팅 중 오류 (설정 행: {cfg.get('row_num', 'N/A')}): {e}", exc_info=True)
                        personalized_message = cfg["message"]  # 실패 시 원본 메시지

                    kwargs = {
                        "chat_id": cfg["chat_id"],
                        "text": personalized_message
                    }
                    # topic_id가 유효한 값일 때 (보통 1 이상, 0이나 None은 아님)
                    if cfg["topic_id"] and cfg["topic_id"] not in [0, 1]: # 1도 General 토픽으로 간주될 수 있으므로 제외
                        kwargs["message_thread_id"] = cfg["topic_id"]
                    
                    try:
                        logger.info(f"[NEW_MEMBER] 환영 메시지 전송 시도: ChatID={cfg['chat_id']}, TopicID={kwargs.get('message_thread_id', 'N/A')}, User={user_info}")
                        sent_msg = bot.send_message(**kwargs)
                        logger.info(f"[NEW_MEMBER] 환영 메시지 전송 성공: MsgID={sent_msg.message_id}, 내용='{personalized_message[:30]}...'")
                    except Exception as e:
                        logger.error(f"[NEW_MEMBER] 환영 메시지 전송 실패 (설정 행: {cfg.get('row_num', 'N/A')}): {e}", exc_info=True)

# --- get_my_user_id 함수 수정 ---
# 기존 get_my_user_id 함수를 찾아서 내부 내용만 아래와 같이 수정합니다.

if bot: # 텔레그램 봇 객체가 있는지 다시 한번 확인
    @bot.message_handler(commands=['myid', 'getid', '나의아이디']) # 'myid', 'getid', '나의아이디' 명령어에 반응
    def get_my_user_id(message):
        """
        사용자의 User ID를 알려주는 핸들러
        """
        user_id = message.from_user.id
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        username = message.from_user.username

        logger.info(f"사용자 {first_name} (ID: {user_id}) 로부터 /myid 명령어 수신.")

        # 사용자 이름, 성 등 MarkdownV2 예약 문자가 포함될 수 있는 부분을 이스케이프 처리
        # User ID(숫자)는 이스케이프 불필요
        # username의 '@'는 @username 형식에서는 예약 문자가 아닙니다.
        escaped_first_name = escape_markdownv2(first_name) if first_name else ''
        escaped_last_name = escape_markdownv2(last_name) if last_name else ''
        # username 자체에 _ 등이 있다면 이스케이프 필요하지만, (@username) 포맷에서는 보통 문제되지 않음.
        # 여기서는 username 자체를 이스케이프하지 않고 포맷에 넣습니다.


        # 응답 메시지 텍스트 구성
        # **굵게** 와 `코드` 문법은 그대로 두고, 문장 끝의 마침표(`.`)는 '\.'로 이스케이프합니다.
        # 사용자 이름 등 변수 자리에는 이스케이프된 내용을 넣습니다.
        response_text_main = f"**{escaped_first_name}** 님의 텔레그램 User ID는 `{user_id}` 입니다\." # 마지막 '.' 이스케이프

        # 추가 정보 (선택 사항) 구성
        user_info_parts_formatted = []
        if escaped_last_name:
            user_info_parts_formatted.append(escaped_last_name)
        if username:
            # @username 형식은 그대로 사용 (username 자체에 _ 등이 있다면 문제가 될 수 있으나 일반적으론 괜찮음)
            user_info_parts_formatted.append(f"(@{username})")

        # 최종 메시지 텍스트 조합
        if user_info_parts_formatted:
             final_response_text = response_text_main + " " + " ".join(user_info_parts_formatted)
        else:
             final_response_text = response_text_main


        logger.debug(f"구성된 응답 메시지 (MarkdownV2): {final_response_text}")


        try:
            # 1. 사용자에게 개인 메시지로 ID 보내기 (우선 시도, 프라이버시 보호)
            # MarkdownV2를 사용하므로 이스케이프된 final_response_text 사용
            bot.send_message(message.from_user.id, final_response_text, parse_mode='MarkdownV2')
            logger.info(f"User ID {user_id}를 개인 메시지로 성공적으로 전송했습니다.")

            # 명령어가 그룹에서 사용되었다면, 그룹에는 확인 메시지만 보냅니다.
            if message.chat.id != message.from_user.id:
                 try:
                     # 그룹 확인 메시지는 MarkdownV2 예약 문자가 포함되지 않도록 간단하게 작성
                     bot.send_message(message.chat.id, f"{first_name} 님의 User ID를 개인 메시지로 보내드렸습니다.", reply_to_message_id=message.message_id)
                     logger.debug(f"그룹 {message.chat.id}에 User ID 개인 메시지 발송 확인 메시지 전송.")
                 except Exception as e_group_ack:
                     logger.error(f"그룹 {message.chat.id}에 확인 메시지 전송 실패: {e_group_ack}", exc_info=True)

        except Exception as e_private_send:
            # 2. 개인 메시지 전송 실패 시 (사용자가 봇에게 먼저 말을 걸지 않은 경우 등)
            logger.warning(f"User ID {user_id}에게 개인 메시지 전송 실패: {e_private_send}. 대신 채팅방 {message.chat.id}으로 전송 시도.")
            try:
                # 명령어가 온 원래 채팅방 (그룹 또는 개인)으로 메시지 전송
                # 이 라인이 traceback에 표시된 라인이며, 여기서도 MarkdownV2를 사용하므로 이스케이프된 텍스트가 필수입니다.
                bot.send_message(message.chat.id, final_response_text, parse_mode='MarkdownV2', reply_to_message_id=message.message_id)
                logger.info(f"User ID {user_id}를 채팅방 {message.chat.id}으로 대신 전송 성공.")
            except Exception as e_group_send:
                 logger.error(f"User ID {user_id}를 채팅방 {message.chat.id}으로 대신 전송 최종 실패: {e_group_send}", exc_info=True)

# -------------------------------------



# ─── 스케줄러 헬퍼 & 루프 ───────────────────────────────────────────────────────
def sleep_until_next_minute():
    now = datetime.now()
    # 다음 분 0초까지 남은 시간 계산 (마이크로초까지 고려)
    sleep_duration = 60 - now.second - (now.microsecond / 1_000_000.0)
    if sleep_duration < 0: # 이미 다음 분으로 넘어간 경우 (거의 발생 안함)
        sleep_duration += 60
    
    # 로깅 추가: 얼마나 대기하는지 확인
    logger.debug(f"[SCHEDULER_SLEEP] 다음 분까지 {sleep_duration:.2f}초 대기합니다.")
    if sleep_duration > 0:
        time.sleep(sleep_duration)


def scheduler_loop():
    logger.info("[SCHEDULER] 스케줄러 루프 시작.")
    initial_load_done = False # 초기 로딩 플래그

    while True:
        try: # 스케줄러 루프 전체를 try-except로 감싸서 에러 발생 시 로깅하고 계속 실행되도록
            if not initial_load_done or (datetime.now(KST).minute % 5 == 0): # 첫 실행 시 또는 매 5분마다 로드
                logger.info("[SCHEDULER] 설정 로드 실행 (최초 또는 5분 주기).")
                load_configs()
                initial_load_done = True
            
            now_kst = datetime.now(KST)
            current_weekday = now_kst.strftime("%A").lower() # 예: "monday"
            current_time_hm = now_kst.strftime("%H:%M")     # 예: "09:30"

            logger.info(f"[SCHEDULER] 현재 시간(KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S %Z%z')}, 요일: {current_weekday}, 시간(HM): {current_time_hm}")

            if not schedule_list:
                logger.info("[SCHEDULER] 실행할 스케줄이 없습니다.")
            else:
                logger.debug(f"[SCHEDULER] 등록된 스케줄 {len(schedule_list)}개 확인 중...")

            for cfg_idx, cfg in enumerate(schedule_list):
                # 로그 레벨을 DEBUG로 설정해야 보임
                logger.debug(f"[SCHEDULER_CHECK] 스케줄 확인 중 (설정 행: {cfg.get('row_num', 'N/A')}): 시트값(요일:{cfg['weekday']}, 시간:{cfg['time']}) vs 현재값(요일:{current_weekday}, 시간:{current_time_hm})")
                
                if cfg["weekday"] == current_weekday and cfg["time"] == current_time_hm:
                    logger.info(f"[SCHEDULER_TRIGGER] 조건 일치! (설정 행: {cfg.get('row_num', 'N/A')}) 메시지 전송 시도: {cfg}")
                    try:
                        kwargs = {
                            "chat_id": cfg["chat_id"],
                            "text": cfg["message"]
                        }
                        if cfg["topic_id"] and cfg["topic_id"] not in [0, 1]:
                            kwargs["message_thread_id"] = cfg["topic_id"]
                        
                        logger.info(f"[SCHEDULER_SENDING] 예약 메시지 전송 시도: ChatID={cfg['chat_id']}, TopicID={kwargs.get('message_thread_id', 'N/A')}, 내용='{cfg['message'][:30]}...'")
                        sent_msg = bot.send_message(**kwargs)
                        logger.info(f"[SCHEDULER_SENT] 예약 메시지 전송 성공: MsgID={sent_msg.message_id}")
                    except Exception as e:
                        logger.error(f"[SCHEDULER_ERROR] 예약 메시지 전송 실패 (설정 행: {cfg.get('row_num', 'N/A')}): {e}", exc_info=True)
            
            sleep_until_next_minute()

        except Exception as e:
            logger.error(f"[SCHEDULER_FATAL] 스케줄러 루프에서 예기치 않은 심각한 오류 발생: {e}", exc_info=True)
            logger.info("[SCHEDULER_FATAL] 1분 후 스케줄러 루프 재시도합니다.")
            time.sleep(60) # 심각한 오류 시 잠시 대기 후 재시도


# ─── 앱 실행 ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not bot:
        logger.critical("텔레그램 봇 토큰이 없어 봇을 실행할 수 없습니다. 환경 변수를 확인하세요.")
        exit(1) # 프로그램 종료

    logger.info("Flask 앱 및 스케줄러 스레드 시작 중...")
    # 1) Flask 헬스체크 서버 (데몬 스레드)
    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False), daemon=True)
    flask_thread.start()
    logger.info(f"Flask 앱이 0.0.0.0:{PORT} 에서 실행됩니다.")

    # 2) 스케줄러 (데몬 스레드)
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()
    logger.info("스케줄러 스레드가 시작되었습니다.")

    # 3) Telegram Polling (메인 스레드에서 실행, 블로킹)
    logger.info("텔레그램 봇 폴링 시작 (무한 대기)...")
    try:
        bot.delete_webhook(drop_pending_updates=True) # 기존 웹훅 제거 및 대기중인 업데이트 삭제
        logger.info("기존 웹훅 제거 완료.")
        bot.infinity_polling(logger_level=logging.INFO, timeout=20, long_polling_timeout=10) # 타임아웃 설정 추가
    except Exception as e:
        logger.critical(f"텔레그램 봇 폴링 중 심각한 오류 발생: {e}", exc_info=True)
    finally:
        logger.info("텔레그램 봇 폴링이 종료되었습니다.")
