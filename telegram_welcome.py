import telebot
import os
from dotenv import load_dotenv

# .env 파일 불러오기
load_dotenv()

# 환경 변수에서 토큰 읽기
TOKEN = os.getenv("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(content_types=['new_chat_members'])
def greet_new_member(message):
    for new_user in message.new_chat_members:
        welcome_message = f"👋 {new_user.first_name}님, 반갑습니다❣️\n비즈LIKE 동아리에 오신걸 환영합니다🎉\n모임 참석 전 상단에 고정돼있는 동아리 소개글을 필독해주세요🙏🙏"
        bot.send_message(message.chat.id, welcome_message)

bot.infinity_polling()
