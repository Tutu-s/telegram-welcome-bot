import telebot

# 봇 토큰
TOKEN = '7906505449:AAGQ2TRjt-Of1Ei7LWXbN-GKqXSlSrLvoYE'

# Bot 객체 생성
bot = telebot.TeleBot(TOKEN)

# 새 멤버 입장 이벤트 감지
@bot.message_handler(content_types=['new_chat_members'])
def greet_new_member(message):
    for new_user in message.new_chat_members:
        welcome_message = f"👋 {new_user.first_name}님, 반갑습니다❣️\n비즈LIKE 동아리에 오신걸 환영합니다🎉\n모임 참석 전 상단에 고정돼있는 동아리 소개글을 필독해주세요🙏🙏"
        bot.send_message(message.chat.id, welcome_message)

# 봇 실행
bot.infinity_polling()
