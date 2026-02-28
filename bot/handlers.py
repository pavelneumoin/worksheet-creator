import os
import requests
import uuid
from telebot.types import Message

# The URL where your Flask backend is running locally
BACKEND_URL = "http://127.0.0.1:3000"

def register_handlers(bot):
    
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message: Message):
        bot.reply_to(message, 
            "Привет! 📚 Я бот Worksheet Creator.\n\n"
            "Пришли мне фотографию (или несколько) с математическими задачами, "
            "и я сгенерирую для тебя рабочий лист в формате PDF!"
        )

    @bot.message_handler(content_types=['photo'])
    def handle_photo(message: Message):
        bot.send_message(message.chat.id, "🤖 Принял фото. Отправляю на распознавание серверу Worksheet Creator...")
        
        try:
            # Get the highest resolution photo
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Save temporarily
            tmp_filename = f"tmp_{uuid.uuid4()}.jpg"
            tmp_filepath = os.path.join(os.path.dirname(__file__), tmp_filename)
            
            with open(tmp_filepath, 'wb') as new_file:
                new_file.write(downloaded_file)
            
            bot.send_message(message.chat.id, "⏳ Распознаю текст и генерирую LaTeX код...")
            
            # Send to backend
            with open(tmp_filepath, 'rb') as f:
                files = {'files': (tmp_filename, f, 'image/jpeg')}
                data = {'topic': 'Рабочий лист (из Telegram)', 'teacher_name': '@' + str(message.from_user.username)}
                
                resp = requests.post(f"{BACKEND_URL}/api/process", files=files, data=data)
            
            # Clean up temp file
            if os.path.exists(tmp_filepath):
                os.remove(tmp_filepath)
                
            if resp.status_code == 200:
                resp_data = resp.json()
                latex_code = resp_data.get('latex_code')
                
                if latex_code:
                    bot.send_message(message.chat.id, "✅ Текст распознан! Компилирую PDF...")
                    
                    # Now compile it
                    compile_resp = requests.post(f"{BACKEND_URL}/api/compile", json={
                        'latex_code': latex_code,
                        'topic': 'Рабочий лист (из Telegram)',
                        'teacher_name': '@' + str(message.from_user.username),
                        'is_variant2': False,
                        'layout': '1col'
                    })
                    
                    if compile_resp.status_code == 200:
                        compile_data = compile_resp.json()
                        pdf_url = compile_data.get('pdf_url')
                        keys_url = compile_data.get('keys_url')
                        
                        # Fetch the actual PDF files from the backend and send them
                        if pdf_url:
                            pdf_resp = requests.get(f"{BACKEND_URL}{pdf_url}")
                            if pdf_resp.status_code == 200:
                                bot.send_document(message.chat.id, ("worksheet.pdf", pdf_resp.content))
                                
                        if keys_url:
                            keys_resp = requests.get(f"{BACKEND_URL}{keys_url}")
                            if keys_resp.status_code == 200:
                                bot.send_document(message.chat.id, ("keys.pdf", keys_resp.content))
                                
                        bot.send_message(message.chat.id, "🎉 Готово! Ваш рабочий лист успешно создан.")
                    else:
                        bot.send_message(message.chat.id, f"❌ Ошибка компиляции PDF: {compile_resp.text}")
                else:
                    bot.send_message(message.chat.id, "❌ Не удалось получить LaTeX код от сервера.")
            else:
                bot.send_message(message.chat.id, f"❌ Ошибка сервера при распознавании: {resp.text}")
                
        except Exception as e:
            bot.reply_to(message, f"❌ Произошла ошибка: {str(e)}")
